"""
Assistant controller - single shared bridge between the PySide6 GUI and the
repaired JARVIS backend, now owning the live audio services.

The controller owns one AudioCaptureService, one VoiceEngine, one
SpeechOutputService and one authoritative VoiceState. Start Voice validates
and opens the real microphone, loads the wake-word model and runs the live
pipeline on instance-held threads/services - nothing is garbage-collected
mid-session. No Qt types live here, so it stays testable headlessly.
"""
import hashlib
import json
import threading
import time
from pathlib import Path

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
from brain.hermes_orchestrator import HermesOrchestrator
from brain.hermes_health import hermes_health
from brain.hermes_adapter import HermesAdapter, HermesAdapterError
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
        self._audit_lock = threading.Lock()
        self._shutdown_event = threading.Event()
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
        self._preloaded_wake_engine = None
        self.agent = DesktopAgent(self)
        self.agent.set_status_callback(lambda s, d: self._emit('agentstatus', s, d))
        self.action_manager = ActionManager(self) # Initialize ActionManager
        self.ctx.assistant_controller = self
        self.ctx.action_manager = self.action_manager
        self.capability_registry = CapabilityRegistry(self)
        self.unified_tool_catalog = UnifiedToolCatalog(self.capability_registry)
        self.unified_tool_router = UnifiedToolRouter()
        self.hermes_adapter = HermesAdapter()
        self.hermes_tasks = HermesTaskManager()
        self.hermes_orchestrator = HermesOrchestrator(
            self.hermes_tasks, self.capability_registry,
            event_callback=self._audit_hermes_event,
        )
        self._hermes_pending_plans = {}
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

    def _audit_hermes_event(self, event, payload=None, **fields):
        """Append metadata-only Hermes evidence to the existing audit log."""
        data = dict(payload or {})
        data.update(fields)
        entry = {
            "timestamp": time.time(),
            "event_type": "hermes",
            "event": str(event),
            "provider": str(getattr(self.hermes_adapter, "provider", "") or ""),
            "model": str(getattr(self.hermes_adapter, "model", "") or ""),
            **data,
        }
        safe = self.action_manager._redact_sensitive_values(entry)
        try:
            with self._audit_lock:
                Config.AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with Config.AUDIT_LOG_FILE.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(safe, ensure_ascii=False) + "\n")
        except Exception as exc:
            audio_log.log_error(f"Failed to write Hermes audit event: {exc}")

    @staticmethod
    def _hermes_plan_hash(plan):
        encoded = json.dumps(
            plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _set_state(self, state, detail=""):
        with self._lock:
            self._state = state
        self._emit("state", state, detail)

    # ---------------------------------------------------------------- settings
    def attach_settings(self, settings_store, initialize_audio=True):
        self._settings = settings_store
        if initialize_audio:
            self.apply_settings()

    def apply_settings(self):
        """Apply runtime-safe settings without restarting JARVIS."""
        if self._settings is None:
            return False
        audio_applied = False
        try:
            audio_applied = bool(self.speech.set_output_device(
                self._settings.get("speaker_device")
            ))
        except Exception as exc:
            audio_log.log_error(f"Unable to apply speaker settings: {exc}", exc)
        try:
            mode = str(self._settings.get("hermes_mode", "disabled") or "disabled").lower()
            enabled = bool(self._settings.get("hermes_enabled", False)) and mode == "cli"
            provider = str(self._settings.get("hermes_provider", "openrouter") or "").strip()
            model = str(self._settings.get("hermes_model", "") or "").strip()
            concurrency = max(1, min(2, int(self._settings.get("hermes_concurrency_limit", 2))))
            self.hermes_adapter.configure(
                enabled=enabled, mode=mode, provider=provider, model=model,
                timeout=Config.HERMES_TIMEOUT_SECONDS,
            )
            self.hermes_tasks.max_concurrent = concurrency
            # Keep shared protocol/status consumers synchronized with the
            # live, non-secret settings. Pilot-locked autonomy stays off.
            Config.HERMES_ENABLED = self.hermes_adapter.enabled
            Config.HERMES_MODE = self.hermes_adapter.mode
            Config.HERMES_PROVIDER = self.hermes_adapter.provider
            Config.HERMES_MODEL = self.hermes_adapter.model
            Config.HERMES_MAX_CONCURRENT_TASKS = concurrency
            Config.HERMES_BACKGROUND_TASKS_ENABLED = False
            Config.HERMES_SCHEDULING_ENABLED = False
            Config.HERMES_LEARNING_ENABLED = False
        except Exception as exc:
            audio_log.log_error(f"Unable to apply Hermes settings: {exc}", exc)
            self.hermes_adapter.configure(
                enabled=False, mode="disabled", provider="", model="",
            )
        self._emit("status", self.status_snapshot())
        return audio_applied

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
            context_state = getattr(self.ctx, "state", {})
            assignment_state = (
                context_state.get("university_assignment")
                if isinstance(context_state, dict) else None
            )
            snap["university_assignment"] = (
                dict(assignment_state) if isinstance(assignment_state, dict) else {}
            )
            openrouter_ready = getattr(self.ctx.llm, "available", False)
            snap["openrouter"] = "ready" if openrouter_ready else "requires configuration"
            snap["openrouter_model"] = Config.OPENROUTER_MODEL
            # Retained as a compatibility key for existing GUI consumers.
            snap["kimi"] = snap["openrouter"]
            hermes = hermes_health(self.hermes_adapter)
            snap["hermes"] = hermes["status"]
            snap["hermes_detail"] = hermes["detail"]
            hermes_task_records = self.hermes_tasks.list()
            hermes_tasks = [task.__dict__.copy() for task in hermes_task_records]
            snap["hermes_tasks"] = hermes_tasks
            displayed_record = self._pick_current_hermes_task(hermes_task_records)
            displayed_hermes = (
                displayed_record.__dict__.copy() if displayed_record else None
            )
            snap["hermes_task"] = displayed_hermes["goal"] if displayed_hermes else "Unavailable"
            snap["hermes_task_status"] = displayed_hermes["status"] if displayed_hermes else "IDLE"
            snap["hermes_steps"] = (f"{displayed_hermes['current_step']}/{displayed_hermes['total_steps']}"
                                     if displayed_hermes else "0/0")
            snap["hermes_progress"] = (
                round(float(displayed_hermes.get("progress", 0.0)) * 100)
                if displayed_hermes else 0
            )
            snap["hermes_capabilities"] = (
                ", ".join(displayed_hermes.get("capabilities_used", [])) or "Unavailable"
                if displayed_hermes else "Unavailable"
            )
            snap["hermes_retries"] = displayed_hermes.get("retries", 0) if displayed_hermes else 0
            snap["hermes_confirmations"] = (
                len(displayed_hermes.get("confirmations", [])) if displayed_hermes else 0
            )
            snap["hermes_output"] = (
                (displayed_hermes.get("output_files") or ["Unavailable"])[-1]
                if displayed_hermes else "Unavailable"
            )
            started = displayed_hermes.get("started_at") if displayed_hermes else None
            ended = displayed_hermes.get("completed_at") if displayed_hermes else None
            snap["hermes_elapsed"] = (
                max(0, round((ended or time.time()) - started, 1)) if started else 0.0
            )
            pending_plan = (
                self._hermes_pending_plans.get(displayed_hermes["task_id"])
                if displayed_hermes else None
            )
            plan_payload = pending_plan[1] if pending_plan else {}
            snap["hermes_plan_summary"] = str(
                plan_payload.get("summary") or "Unavailable"
            )
            snap["hermes_requested_capabilities"] = (
                ", ".join(dict.fromkeys(
                    str(step.get("capability_id") or "")
                    for step in plan_payload.get("steps", [])
                    if step.get("capability_id")
                )) or "Unavailable"
            )
            snap["hermes_approval_pending"] = bool(
                displayed_hermes
                and displayed_hermes["status"] == "WAITING_CONFIRMATION"
                and pending_plan
            )
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
            # This is an explicit/background maintenance operation.  External
            # Hermes metadata is refreshed here, never in the frequent GUI
            # status snapshot.
            self.unified_tool_catalog.refresh()
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

    def open_hermes_provider_setup(self):
        from brain.hermes_runtime_manager import HermesRuntimeManager
        result = HermesRuntimeManager().open_provider_setup()
        self._emit("hermes_configuration", result)
        return result

    def plan_hermes_task(self, goal, user_request, capabilities=None):
        """Request and retain one constrained plan; never execute it here."""
        if not self.hermes_adapter.enabled or self.hermes_adapter.mode != "cli":
            raise RuntimeError("Hermes planning is disabled")
        if not self.capability_registry.snapshot():
            self.capability_registry.discover()
            self.capability_registry.run_health_checks()
        request = self.hermes_orchestrator.prepare_request(
            goal, user_request, capabilities,
        )
        if not request.available_capabilities:
            raise RuntimeError("No healthy pilot capabilities are available")
        task = self.hermes_tasks.create(request.goal)
        self.hermes_tasks.transition(task.task_id, "PLANNING")
        allowed_ids = [
            str(item.get("capability_id") or "")
            for item in request.available_capabilities
            if item.get("capability_id")
        ]
        explicitly_requested = [
            str(item.get("capability_id") or item.get("id") or "")
            for item in (capabilities or []) if isinstance(item, dict)
        ]
        requested_ids = explicitly_requested or allowed_ids
        self._audit_hermes_event(
            "task_received", task_id=task.task_id,
            goal_length=len(str(goal)), request_length=len(str(user_request)),
            capabilities_requested=requested_ids,
            capabilities_allowed=allowed_ids,
            capabilities_rejected=sorted(set(requested_ids) - set(allowed_ids)),
        )
        try:
            payload = self.hermes_adapter.plan(request)
            plan, task = self.hermes_orchestrator.accept_plan(
                request, payload, task_id=task.task_id,
            )
            with self._lock:
                current = self.hermes_tasks.get(task.task_id)
                if current is None or current.cancellation_token:
                    raise HermesAdapterError("request cancelled")
                self._hermes_pending_plans[task.task_id] = (request, plan)
            self._audit_hermes_event(
                "plan_accepted", task_id=task.task_id,
                plan_hash=self._hermes_plan_hash(plan),
                step_count=len(plan.get("steps", [])),
                capabilities_requested=[
                    str(step.get("capability_id") or "")
                    for step in plan.get("steps", [])
                ],
            )
        except Exception as exc:
            current = self.hermes_tasks.get(task.task_id)
            # A pre-emptive GUI/voice cancellation terminates the owned CLI
            # process.  When that blocked call unwinds, its expected exception
            # must not rewrite the already-terminal CANCELLED state as FAILED.
            if current is None or not current.cancellation_token:
                self.hermes_tasks.transition(task.task_id, "FAILED", error=str(exc))
            self._audit_hermes_event(
                "planning_failed", task_id=task.task_id,
                status="CANCELLED" if current and current.cancellation_token else "FAILED",
                error=str(exc),
            )
            raise
        self._emit("status", self.status_snapshot())
        return request, plan, task

    @staticmethod
    def _validate_hermes_step_parameters(step):
        capability_id = str(step.get("capability_id") or "")
        params = dict(step.get("parameters") or {})
        if capability_id == "research.search_web":
            query = str(params.get("query") or "").strip()
            if not query or len(query) > 500:
                raise ValueError("Hermes research query is invalid")
            params["query"] = query
            params["limit"] = max(1, min(int(params.get("limit", 6)), 10))
        elif capability_id == "research.read_source":
            url = str(params.get("url") or "").strip()
            if not url or len(url) > 2048:
                raise ValueError("Hermes source URL is invalid")
            params["url"] = url
            params["max_chars"] = max(200, min(int(params.get("max_chars", 3500)), 6000))
        elif capability_id == "research.summarize_sources":
            sources = params.get("sources")
            if not isinstance(sources, list) or len(sources) > 10:
                raise ValueError("Hermes sources must be a bounded list")
        elif capability_id == "office_word.create_document":
            if params:
                raise ValueError("Hermes blank document creation takes no parameters")
        elif capability_id == "office_word.insert_text":
            text = str(params.get("text") or "")
            if not text or len(text) > 20_000:
                raise ValueError("Hermes Word text is invalid")
            params = {"text": text}
        elif capability_id == "office_word.save_document":
            raw_path = Path(str(params.get("path") or ""))
            if not raw_path.is_absolute():
                raise ValueError("Hermes output path must be absolute")
            path = raw_path.resolve()
            root = Config.TEMP_DIR.resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ValueError("Hermes output path is outside the approved temp directory") from exc
            params = {"path": str(path)}
        return params

    def _execute_hermes_step(self, step):
        """Execute one validated step only through ActionManager's allowlist."""
        params = self._validate_hermes_step_parameters(step)
        action = Action(
            action_id=str(step["step_id"]), skill=str(step["skill"]),
            operation=str(step["operation"]), parameters=params,
            permission_scope=str(step["permission_scope"]),
            risk_level=str(step["risk_level"]),
            requires_confirmation=bool(step["requires_confirmation"]),
            reversible=bool(step["reversible"]), rollback_action=None,
        )
        result = self.action_manager.execute_action(action)
        capability_id = str(step["capability_id"])
        if capability_id == "research.search_web":
            ok = isinstance(result, list) and bool(result)
        elif capability_id == "research.read_source":
            ok = isinstance(result, dict) and bool(str(result.get("text") or "").strip())
        elif capability_id == "research.summarize_sources":
            ok = isinstance(result, str) and bool(result.strip())
        else:
            text = str(result or "").lower()
            ok = bool(result is not None and not any(
                marker in text for marker in ("couldn't", "failed", "denied", "cancelled")
            ))
        output_files = []
        if capability_id == "office_word.save_document" and ok:
            path = Path(params["path"])
            if path.is_file():
                output_files.append(str(path))
            else:
                ok = False
        return {
            "ok": ok, "result": result, "output_files": output_files,
            "error": "JARVIS could not verify the step success condition" if not ok else "",
        }

    def run_approved_hermes_plan(self, request, plan, task_id, *, approved):
        try:
            return self.hermes_orchestrator.run_approved_plan(
                request, plan, self._execute_hermes_step,
                approved=bool(approved), task_id=task_id,
            )
        finally:
            with self._lock:
                self._hermes_pending_plans.pop(task_id, None)
            self._emit("status", self.status_snapshot())

    def _select_hermes_task(self, selector="current"):
        tasks = sorted(self.hermes_tasks.list(), key=lambda item: item.created_at)
        if not tasks:
            return None
        value = str(selector or "current").strip().lower()
        if value in {"", "current", "active", "latest", "last"}:
            return self._pick_current_hermes_task(tasks)
        status_selectors = {
            "running": {"RUNNING", "RETRYING"},
            "paused": {"PAUSED"},
            "planning": {"PLANNING"},
            "waiting": {"WAITING_CONFIRMATION"},
            "approval": {"WAITING_CONFIRMATION"},
            "queued": {"QUEUED"},
            "completed": {"COMPLETED"},
            "failed": {"FAILED"},
            "cancelled": {"CANCELLED"},
            "canceled": {"CANCELLED"},
        }
        selected_statuses = status_selectors.get(value)
        if selected_statuses:
            matching = [task for task in tasks if task.status in selected_statuses]
            return self._pick_latest_created_hermes_task(matching)
        numbers = {
            "one": 1, "first": 1, "two": 2, "second": 2,
            "three": 3, "third": 3, "four": 4, "fourth": 4,
        }
        try:
            index = numbers.get(value, int(value) if value.isdigit() else 0)
        except (TypeError, ValueError):
            index = 0
        if 1 <= index <= len(tasks):
            return tasks[index - 1]
        exact = next((task for task in tasks if task.task_id == value), None)
        return exact

    @staticmethod
    def _pick_current_hermes_task(tasks):
        """Select the one task Mission Control and `current` commands share."""
        tasks = list(tasks or [])
        if not tasks:
            return None
        active = [
            task for task in tasks
            if task.status not in {"COMPLETED", "FAILED", "CANCELLED"}
        ]
        if active:
            return AssistantController._pick_latest_created_hermes_task(active)
        return max(
            enumerate(tasks),
            key=lambda item: (
                item[1].updated_at, item[1].created_at, item[0],
            ),
        )[1]

    @staticmethod
    def _pick_latest_created_hermes_task(tasks):
        tasks = list(tasks or [])
        if not tasks:
            return None
        return max(
            enumerate(tasks),
            key=lambda item: (
                item[1].created_at, item[1].updated_at, item[0],
            ),
        )[1]

    def _hermes_status_text(self):
        snapshot = self.status_snapshot()
        state = str(snapshot.get("hermes") or "unavailable").replace("_", " ")
        detail = str(snapshot.get("hermes_detail") or "").strip()
        task = str(snapshot.get("hermes_task") or "Unavailable")
        task_state = str(snapshot.get("hermes_task_status") or "IDLE")
        return (
            f"Hermes is {state}. {detail}. "
            f"The displayed task is {task}, with status {task_state}."
        )

    def _hermes_tasks_text(self):
        tasks = sorted(self.hermes_tasks.list(), key=lambda item: item.created_at)
        if not tasks:
            return "Hermes has no recorded tasks."
        parts = []
        for index, task in enumerate(tasks, 1):
            progress = round(float(task.progress or 0.0) * 100)
            parts.append(
                f"Task {index}, {task.goal}, is {task.status.lower()} at {progress} percent"
            )
        return "Hermes tasks: " + "; ".join(parts) + "."

    def handle_hermes_intent(self, skill, params=None):
        """Handle registered Hermes commands without bypassing JARVIS policy."""
        params = dict(params or {})
        if skill == "hermes.status":
            return self._hermes_status_text()
        if skill == "hermes.tasks":
            return self._hermes_tasks_text()
        if skill == "hermes.plan":
            goal = str(params.get("goal") or "").strip()
            if not goal:
                return "Please give Hermes a specific goal to plan."
            if len(goal) > 4000:
                return "That Hermes goal is too long. Please keep it under 4,000 characters."
            if not self.hermes_adapter.enabled or self.hermes_adapter.mode != "cli":
                self._audit_hermes_event(
                    "planning_skipped", status="DISABLED", goal_length=len(goal),
                )
                return (
                    "Hermes planning is disabled. Enable the external Hermes engine "
                    "in Settings after its provider is configured. Normal JARVIS commands remain available."
                )
            try:
                _request, plan, task = self.plan_hermes_task(goal, goal)
            except Exception as exc:
                safe = self.action_manager._redact_text(exc)
                return f"Hermes could not prepare the plan: {safe}. No action was executed."
            capabilities = ", ".join(
                dict.fromkeys(step["capability_id"] for step in plan["steps"])
            ) or "none"
            summary = str(plan.get("summary") or "Plan prepared").strip()[:500]
            background_note = (
                " Background execution remains disabled; this is a reviewable plan "
                "only, and APPROVE ONCE runs it interactively."
            ) if (
                params.get("background_requested")
                and not Config.HERMES_BACKGROUND_TASKS_ENABLED
            ) else ""
            return (
                f"Hermes prepared a {len(plan['steps'])}-step plan for task "
                f"{task.task_id}: {summary}. Requested capabilities: {capabilities}. "
                f"The plan is waiting for JARVIS approval and nothing has executed."
                f"{background_note}"
            )

        task = self._select_hermes_task(params.get("task"))
        if task is None:
            return "I could not find that Hermes task."
        if skill in {"hermes.approve", "hermes.deny"}:
            with self._lock:
                pending = self._hermes_pending_plans.get(task.task_id)
            if task.status != "WAITING_CONFIRMATION" or pending is None:
                return f"Hermes task {task.task_id} has no plan waiting for approval."
            request, plan = pending
            approved = skill == "hermes.approve"
            _plan, updated, results = self.run_approved_hermes_plan(
                request, plan, task.task_id, approved=approved,
            )
            if not approved:
                return f"Hermes task {updated.task_id} was denied and cancelled."
            if updated.status == "COMPLETED":
                output = updated.output_files[-1] if updated.output_files else "no output file"
                return (
                    f"Hermes task {updated.task_id} completed {updated.current_step} "
                    f"verified steps through JARVIS. Output: {output}."
                )
            return (
                f"Hermes task {updated.task_id} stopped with status "
                f"{updated.status.lower()}: {updated.last_error or 'no verified result'}."
            )
        if skill == "hermes.pause":
            if task.status not in {"RUNNING", "RETRYING"}:
                return f"Hermes task {task.task_id} cannot be paused while it is {task.status.lower()}."
            updated = self.hermes_tasks.pause(task.task_id)
            self._emit("status", self.status_snapshot())
            return f"Hermes task {updated.task_id} is paused."
        if skill == "hermes.resume":
            if task.status != "PAUSED":
                return f"Hermes task {task.task_id} is not paused; it is {task.status.lower()}."
            updated = self.hermes_tasks.resume(task.task_id)
            self._emit("status", self.status_snapshot())
            return f"Hermes task {updated.task_id} resumed."
        if skill == "hermes.cancel":
            if task.status in {"COMPLETED", "FAILED", "CANCELLED"}:
                return f"Hermes task {task.task_id} is already {task.status.lower()}."
            if task.status == "PLANNING":
                self.hermes_adapter.cancel()
            with self._lock:
                updated = self.hermes_tasks.cancel(task.task_id)
                self._hermes_pending_plans.pop(task.task_id, None)
            self._audit_hermes_event(
                "task_cancelled", task_id=task.task_id,
                prior_status=task.status, source="user_command",
            )
            self._emit("status", self.status_snapshot())
            return f"Hermes task {updated.task_id} was cancelled."
        return "That Hermes command is not registered."

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
        if command.startswith("/trace "):
            from core.command_trace import format_trace
            return format_trace(cleaned.strip()[7:].strip(), self.ctx)
        if command not in {"/help", "/skills", "/status", "/capabilities", "/selftest"}:
            return None
        if command == "/help":
            return ("Registry commands: /help, /skills, /status, "
                    "/capabilities, /selftest, /trace <command>")
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

    def preload_wake_model(self):
        """Load the local wake model while the visible startup shell is shown."""
        if self._shutdown_event.is_set():
            return False
        try:
            with self._lock:
                if self._preloaded_wake_engine is None:
                    from voice.wakeword import WakeWordEngine
                    self._preloaded_wake_engine = WakeWordEngine(
                        model_name=Config.WAKE_WORD,
                        threshold=Config.WAKE_THRESHOLD,
                    )
                wake_engine = self._preloaded_wake_engine
            loaded = bool(wake_engine._ensure_loaded())
            if loaded:
                audio_log.log("Controller: wake model preloaded")
            else:
                audio_log.log_error(
                    "Controller: wake model preload failed",
                    wake_engine.load_error,
                )
            return loaded
        except Exception as exc:
            audio_log.log_error(f"Controller: wake model preload failed: {exc}", exc)
            return False

    def start_voice(self):
        audio_log.log("Controller: Start Voice requested")
        if self._shutdown_event.is_set():
            audio_log.log("Controller: Start Voice ignored during shutdown")
            return False
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

        # Publish the engine under the controller lock before starting it so
        # concurrent shutdown can always signal an in-flight model load.
        with self._lock:
            if self._shutdown_event.is_set():
                return False
            if self.voice_engine is None:
                self.voice_engine = VoiceEngine(
                    self, self.state, self.speech,
                    device_index=mic["index"],
                    wake_engine=self._preloaded_wake_engine,
                )
            else:
                self.voice_engine.capture.device_index = mic["index"]
            engine = self.voice_engine
        engine.set_diagnostic(self.voice_diagnostic)

        ok = engine.start()
        if self._shutdown_event.is_set():
            engine.stop()
            return False
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
        if isinstance(getattr(self.ctx, "state", None), dict):
            self.ctx.state["input_source"] = "voice" if from_voice else "typed"
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
                if not cleaned.lower().startswith("/trace "):
                    self.speak(spoken)

        except Exception as exc:
            audio_log.log_error("Shared command pipeline failed", exc)
            if self.debug:
                import traceback
                traceback.print_exc()
            spoken = f"The command pipeline failed locally: {exc}"
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
            voice = self.state.snapshot()
            if voice.get("microphone_active") and voice.get("wakeword_active"):
                self._set_state(STATE_LISTENING_WAKE, "Waiting for Hey Jarvis")
            else:
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
        active_hermes = [
            task for task in self.hermes_tasks.list()
            if task.status not in {"COMPLETED", "FAILED", "CANCELLED"}
        ]
        try:
            self.hermes_adapter.cancel()
        except Exception:
            pass
        try:
            self.hermes_tasks.cancel_all()
        except Exception:
            pass
        with self._lock:
            self._hermes_pending_plans.clear()
        for task in active_hermes:
            self._audit_hermes_event(
                "task_cancelled", task_id=task.task_id,
                prior_status=task.status, source="global_stop",
            )
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
        self._shutdown_event.set()
        active_hermes = [
            task for task in self.hermes_tasks.list()
            if task.status not in {"COMPLETED", "FAILED", "CANCELLED"}
        ]
        try:
            self.hermes_adapter.cancel()
        except Exception:
            pass
        try:
            self.hermes_tasks.cancel_all()
        except Exception:
            pass
        with self._lock:
            self._hermes_pending_plans.clear()
        for task in active_hermes:
            self._audit_hermes_event(
                "task_cancelled", task_id=task.task_id,
                prior_status=task.status, source="shutdown",
            )
        try:
            with self._lock:
                engine = self.voice_engine
            if engine is not None:
                engine.stop()
        except Exception:
            pass
        try:
            self.speech.close()
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
