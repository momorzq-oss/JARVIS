"""
Assistant controller - single shared bridge between the PySide6 GUI and the
repaired JARVIS backend, now owning the live audio services.

The controller owns one AudioCaptureService, one VoiceEngine, one
SpeechOutputService and one authoritative VoiceState. Start Voice validates
and opens the real microphone, loads the wake-word model and runs the live
pipeline on instance-held threads/services - nothing is garbage-collected
mid-session. No Qt types live here, so it stays testable headlessly.
"""
import threading

from config import Config, ensure_dirs
from voice import audio_log
from voice.devices import resolve_microphone, resolve_speaker
from voice.voice_state import VoiceState
from voice.speech_service import SpeechOutputService
from voice.speaker import Speaker
from voice.engine import VoiceEngine
from core.desktop_agent import DesktopAgent
from core.action_manager import Action, ActionManager
from core.capability_registry import CapabilityRegistry
from core.unified_tool_catalog import UnifiedToolCatalog
from core.unified_tool_router import UnifiedToolRouter
from brain.hermes_task_manager import HermesTaskManager
from brain.hermes_health import hermes_health
from core.account_connections import AccountConnectionManager

STATE_IDLE = "idle"
STATE_LOADING = "loading"
STATE_LISTENING_WAKE = "listening_wake"
STATE_WAKE_DETECTED = "wake_detected"
STATE_RECORDING = "recording"
STATE_PROCESSING = "processing"
STATE_SPEAKING = "speaking"
STATE_READY = "ready"
STATE_ERROR = "error"


class AssistantController:
    def __init__(self, ctx=None, skip_preload=False, debug=False,
                 voice_diagnostic=False):
        ensure_dirs()
        self.debug = debug
        self.skip_preload = skip_preload
        self._callbacks = {}
        self._lock = threading.RLock()
        self._state = STATE_IDLE
        self._last_command = ""
        self._last_response = ""
        self._current_task = ""
        self.voice_diagnostic = voice_diagnostic

        audio_log.log("Controller created")

        if ctx is not None:
            self.ctx = ctx
        else:
            from main import AssistantContext
            self.ctx = AssistantContext()
            self.ctx.debug = debug

        # ---- shared audio services --------------------------------------
        self.state = VoiceState()
        if isinstance(self.ctx.speaker, SpeechOutputService):
            self.speech = self.ctx.speaker
            self.speech.attach(self.speech.speaker, self.state)
        elif isinstance(self.ctx.speaker, Speaker):
            self.speech = SpeechOutputService(self.ctx.speaker, self.state)
            self.speech.note_engine()
        else:
            self.speech = self.ctx.speaker
        self.speaker = self.speech

        self.voice_engine = None      # created on first Start Voice, then reused
        self.agent = DesktopAgent(self)
        self.agent.set_status_callback(lambda s, d: self._emit('agentstatus', s, d))
        self.action_manager = ActionManager(self) # Initialize ActionManager
        self.ctx.assistant_controller = self
        self.ctx.action_manager = self.action_manager
        self.capability_registry = CapabilityRegistry(self)
        self.unified_tool_catalog = UnifiedToolCatalog(self.capability_registry)
        self.unified_tool_router = UnifiedToolRouter()
        self.hermes_tasks = HermesTaskManager()
        self.account_connections = AccountConnectionManager(self.ctx)
        live_task = getattr(self.ctx, "live_task", None)
        if live_task is not None:
            live_task._on_change = lambda snapshot: self._emit("taskstatus", snapshot)
        self._settings = None

    # ---------------------------------------------------------------- events
    def set_callback(self, name, fn):
        self._callbacks[name] = fn

    def _emit(self, name, *args):
        fn = self._callbacks.get(name)
        if fn is None:
            return
        try:
            fn(*args)
        except Exception:
            pass

    def _log(self, tag, msg):
        self._emit("log", tag, msg)

    def _set_state(self, state, detail=""):
        with self._lock:
            self._state = state
        self._emit("state", state, detail)

    # ---------------------------------------------------------------- settings
    def attach_settings(self, settings_store):
        self._settings = settings_store
        self.apply_settings()

    def apply_settings(self):
        """Apply runtime-safe settings without restarting JARVIS."""
        if self._settings is None:
            return False
        try:
            return bool(self.speech.set_output_device(
                self._settings.get("speaker_device")
            ))
        except Exception as exc:
            audio_log.log_error(f"Unable to apply speaker settings: {exc}", exc)
            return False

    def _saved_mic(self):
        if self._settings is None:
            return None
        return self._settings.get("microphone_device")

    @property
    def speaker_device(self):
        saved = self._settings.get("speaker_device") if self._settings is not None else None
        return resolve_speaker(saved)

    # ---------------------------------------------------------------- status
    def status_snapshot(self):
        try:
            self.speech.sync_state()
        except Exception:
            pass
        snap = self.state.snapshot()
        with self._lock:
            try:
                registry_items = self.ctx.registry.get_status()
                snap["sessions"] = len(registry_items)
            except Exception:
                registry_items = []
                snap["sessions"] = 0
            snap["state"] = self._state
            snap["last_command"] = self._last_command
            snap["last_response"] = self._last_response
            snap["current_task"] = self._current_task
            openrouter_ready = getattr(self.ctx.llm, "available", False)
            snap["openrouter"] = "ready" if openrouter_ready else "requires configuration"
            snap["openrouter_model"] = Config.OPENROUTER_MODEL
            # Retained as a compatibility key for existing GUI consumers.
            snap["kimi"] = snap["openrouter"]
            hermes = hermes_health()
            snap["hermes"] = hermes["status"]
            snap["hermes_detail"] = hermes["detail"]
            hermes_tasks = [task.__dict__.copy() for task in self.hermes_tasks.list()]
            snap["hermes_tasks"] = hermes_tasks
            active_hermes = next((task for task in hermes_tasks if task["status"] not in {"COMPLETED", "FAILED", "CANCELLED"}), None)
            snap["hermes_task"] = active_hermes["goal"] if active_hermes else "Unavailable"
            snap["hermes_steps"] = (f"{active_hermes['current_step']}/{active_hermes['total_steps']}"
                                     if active_hermes else "0/0")
            snap["unified_tools"] = self.unified_tool_catalog.report()
            snap["browser"] = "open" if self._browser_open() else "closed"
            snap["desktop_agent"] = "ready"
            names = " ".join(
                f"{item.get('name', '')} {item.get('window_title', '')}".lower()
                for item in registry_items
            )
            snap["word"] = "open" if "word" in names else "closed"
            snap["excel"] = "open" if "excel" in names else "closed"
            snap["powerpoint"] = (
                "open" if "powerpoint" in names or "powerpnt" in names else "closed"
            )
            snap["memory"] = "ready" if Config.MEMORY_FILE.exists() else "empty"
            snap["research"] = (
                "active" if getattr(self.ctx, "pending", None)
                and self.ctx.pending.get("kind") == "research" else "idle"
            )
            snap["news"] = "ready" if Config.NEWS_CACHE_FILE.exists() else "idle"
            try:
                from core.capability_health import CapabilityHealth
                snap["system_metrics"] = CapabilityHealth(self).system_metrics()
            except Exception as exc:
                snap["system_metrics"] = {"status": "DEGRADED", "detail": str(exc)}
        return snap

    def _browser_open(self):
        try:
            page = getattr(self.ctx.browser, "_page", None)
            return page is not None and not page.is_closed()
        except Exception:
            return False

    def registry_items(self):
        try:
            return self.ctx.registry.get_status()
        except Exception:
            return []

    def start_capability_scan(self):
        try:
            self.capability_registry.discover()
            self.capability_registry.run_health_checks()
            self._emit("capabilities", self.capability_registry.report())
            return True
        except Exception as exc:
            audio_log.log_error(f"Capability scan degraded: {exc}", exc)
            self._emit("capabilities", {
                "total": 0, "counts": {"DEGRADED": 1},
                "error": str(exc), "capabilities": [],
            })
            return False

    def begin_account_login(self, account):
        result = self.account_connections.begin_login(account)
        self._emit("account_connection", str(account), result)
        self.start_capability_scan()
        return result

    def verify_account_login(self, account):
        result = self.account_connections.verify(account)
        self._emit("account_connection", str(account), result)
        self.start_capability_scan()
        return result

    def preload_models(self):
        if self.skip_preload:
            audio_log.log("Controller: model preload skipped")
            return False
        try:
            from main import preload_models
            preload_models(self.ctx)
            return True
        except Exception as exc:
            audio_log.log_error(f"Controller preload degraded: {exc}", exc)
            return False

    def _registry_command(self, cleaned):
        command = cleaned.strip().lower()
        if command not in {"/help", "/skills", "/status", "/capabilities", "/selftest"}:
            return None
        if command == "/help":
            return ("Registry commands: /help, /skills, /status, "
                    "/capabilities, /selftest")
        if command == "/skills":
            return self.capability_registry.skills_text()
        if command == "/capabilities":
            return self.capability_registry.capabilities_text()
        if command == "/selftest":
            self.start_capability_scan()
            report = self.capability_registry.report()
            return f"Self-test complete: {report['total']} capabilities; {report['counts']}"
        snapshot = self.status_snapshot()
        report = self.capability_registry.report()
        return (f"State: {snapshot.get('state')}; sessions: {snapshot.get('sessions')}; "
                f"capabilities: {report['total']}; health: {report['counts']}")

    # ---------------------------------------------------------------- devices
    def enumerate_devices(self):
        from voice.devices import list_devices
        return list_devices()

    def refresh_devices(self):
        mic, _ = resolve_microphone(self._saved_mic())
        spk, _ = resolve_speaker()
        if mic is not None:
            self.state.update(microphone_available=True,
                              selected_microphone=mic["name"])
        else:
            self.state.update(microphone_available=False,
                              selected_microphone="")
        self._emit("status", self.status_snapshot())
        return mic, spk

    @property
    def voice_running(self):
        return self.voice_engine is not None and self.voice_engine.running

    def start_voice(self):
        audio_log.log("Controller: Start Voice requested")
        if self.voice_running:
            self._emit("status", "Voice is not running")
            return True
        mic, err = resolve_microphone(self._saved_mic())
        if mic is None:
            self._set_state(STATE_ERROR, err)
            self._emit("status", f"Audio error: {err}")
            audio_log.log_error("Controller: Audio ERROR", err)
            audio_log.log_error(err)
            return False
        self.state.update(selected_microphone=mic["name"], microphone_available=True)
        self._set_state(STATE_LOADING, f"Opening {mic['name']}")

        # create engine once, reuse across restarts
        if self.voice_engine is None:
            self.voice_engine = VoiceEngine(
                self, self.state, self.speech,
                device_index=mic["index"],
            )
        else:
            self.voice_engine.capture.device_index = mic["index"]
        self.voice_engine.set_diagnostic(self.voice_diagnostic)

        ok = self.voice_engine.start()
        if not ok:
            err = self.state.last_audio_error or "voice startup failed"
            self._emit("voicestate", self.state.snapshot())
            self._emit("status", f"Voice error: {err}")
            self._set_state(STATE_ERROR, err)
            return False
        self._set_state(STATE_LISTENING_WAKE, "Listening for Hey Jarvis")
        self._emit("voicestate", self.state.snapshot())
        self._emit("wakeword", "ready")
        self._emit("status", self.status_snapshot())
        return True

    def stop_voice(self):
        if not self.voice_running:
            self._emit("status", "Voice is not running")
            return False
        self.voice_engine.stop()
        self._set_state(STATE_IDLE, "Voice stopped")
        self._emit("voicestate", self.state.snapshot())
        self._emit("status", self.status_snapshot())
        return True

    # ---------------------------------------------------------------- command
    def handle_text(self, text, from_voice=False):
        import main as main_mod
        try:
            from core.command_text import cleanup_command
            cleaned = cleanup_command(text)
        except Exception:
            cleaned = text
        if not cleaned:
            return None
        with self._lock:
            self._last_command = cleaned
            self._current_task = cleaned
        self._set_state(STATE_PROCESSING, cleaned)
        self._emit("timeline", "heard", text)
        self._emit("timeline", "cleaned", cleaned)
        try:
            spoken = self._registry_command(cleaned)
            if spoken is None:
                spoken = main_mod.handle_utterance(cleaned, self.ctx)
            else:
                # The normal utterance pipeline speaks its own responses.
                # Registry commands bypass it, so play this one response here.
                self.speak(spoken)

        except Exception as exc:
            if self.debug:
                import traceback
                traceback.print_exc()
            spoken = f"Something went wrong, sir: {exc}"
            self._emit("timeline", "failed", str(exc))
            self._set_state(STATE_ERROR, str(exc))
        with self._lock:
            self._current_task = ""
            if spoken:
                self._last_response = spoken
        if spoken:
            self._emit("response", spoken)
            self._emit("timeline", "completed", spoken[:120])
        # self.speech.note_engine() # Removed this call as it belongs inside real SpeechOutputService or its setup
        self._emit("registry", self.registry_items())
        self._emit("voicestate", self.state.snapshot())
        self._emit("status", self.status_snapshot())
        if self._state != STATE_ERROR:
            self._set_state(STATE_READY, "Ready")
        return spoken

    # ---------------------------------------------------------------- speech
    def speak(self, text, block=False):
        self.speech.speak(text, block=block)
        self._emit("voicestate", self.state.snapshot())

    def mute_speech(self):
        self.speech.mute()
        self.state.update(speaker_state="muted")
        self._emit("voicestate", self.state.snapshot())

    def unmute_speech(self):
        self.speech.unmute()
        self.state.update(speaker_state="ready")
        self._emit("voicestate", self.state.snapshot())

    @property
    def speech_muted(self):
        return self.speech.muted

    def stop_task(self):
        """Emergency stop for mouse/keyboard automation."""
        try:
            self.agent.request_stop()
        except Exception:
            pass
        try:
            live_task = getattr(self.ctx, "live_task", None)
            if live_task is not None:
                live_task.cancel()
        except Exception:
            pass
        try:
            self.hermes_tasks.cancel_all()
        except Exception:
            pass
        self._emit("agentstatus", "Cancelled", "stopped by user")
        return True

    def confirm(self, action: Action):
        """Route a sensitive-action confirmation to the GUI handler."""
        return self.agent.confirm(action)

    def close_all(self):
        try:
            return self.ctx.registry.close_all()
        except Exception:
            return []

    # ---------------------------------------------------------------- shutdown
    def shutdown(self):
        audio_log.log("Controller shutdown requested")
        try:
            if self.voice_engine is not None:
                self.voice_engine.stop()
        except Exception:
            pass
        try:
            self.speech.stop()
        except Exception:
            pass
        try:
            pipeline = getattr(self.ctx, "pipeline", None)
            if pipeline is not None:
                pipeline.close()
        except Exception:
            pass
        try:
            self.ctx.browser.close_browser()
        except Exception:
            pass
        self._set_state(STATE_IDLE, "Shut down")
        audio_log.log("Controller shutdown complete")
