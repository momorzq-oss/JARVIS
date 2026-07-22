"""
Bridge between the AssistantController (backend threads) and the Qt GUI.

A single ControllerBridge QObject lives on the GUI thread and exposes Qt
signals. The controller's plain callbacks forward onto these signals, which
Qt delivers to GUI-thread slots - so background threads never touch widgets
directly. Long operations (typed commands, voice, preload) run on a
QThreadPool so the GUI thread never blocks.
"""
import json
import queue
import re
import threading

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QRunnable,
    QThreadPool,
    Signal,
    Slot,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import QLabel, QDialog, QVBoxLayout, QPushButton

from core.action_manager import Action


CONFIRMATION_EVENT_TYPE = QEvent.Type(QEvent.registerEventType())


class _ConfirmationEvent(QEvent):
    def __init__(self, action):
        super().__init__(CONFIRMATION_EVENT_TYPE)
        self.action = action


class ControllerBridge(QObject):
    stateChanged = Signal(str, str)          # state, detail
    statusChanged = Signal(object)           # dict | str
    transcription = Signal(str)
    response = Signal(str)
    timeline = Signal(str, str)              # stage, text
    registry = Signal(object)                # list of dict
    logLine = Signal(str, str)               # tag, message
    wakeword = Signal(str)                   # phase
    voicestate = Signal(object)             # VoiceState.snapshot dict
    agentstatus = Signal(str, str)           # status, detail
    capabilities = Signal(object)            # capability registry report
    taskstatus = Signal(object)              # live task snapshot
    # New signal for confirmation requests
    confirmationRequested = Signal(Action)
    confirmationResult = Signal(str)
    state_changed = Signal(str, str)
    voice_state_changed = Signal(object)
    microphone_level_changed = Signal(float)
    wake_word_state_changed = Signal(str)
    transcript_changed = Signal(str)
    cleaned_command_changed = Signal(str)
    planner_state_changed = Signal(str, str)
    hermes_state_changed = Signal(str, str)
    task_started = Signal(object)
    task_progress = Signal(object)
    task_step_started = Signal(object)
    task_step_completed = Signal(object)
    task_step_failed = Signal(object)
    task_waiting_confirmation = Signal(object)
    task_completed = Signal(object)
    task_cancelled = Signal(object)
    task_failed = Signal(object)
    speech_started = Signal()
    speech_level_changed = Signal(float)
    speech_finished = Signal()
    capability_status_changed = Signal(object)
    application_opened = Signal(object)
    application_focused = Signal(object)
    application_closed = Signal(object)
    browser_state_changed = Signal(object)
    office_state_changed = Signal(object)
    research_state_changed = Signal(object)
    system_metrics_changed = Signal(object)
    audit_event = Signal(str, str)
    emergency_stop_triggered = Signal()
    news_items_changed = Signal(object)
    account_connection_changed = Signal(str, object)


class _Task(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    @Slot()
    def run(self):
        try:
            self._fn(*self._args, **self._kwargs)
        except Exception:
            pass # TODO: log this


class GuiController(QObject):
    """Owns the AssistantController + bridge; GUI talks only to this."""

    def __init__(self, controller=None, skip_preload=False, debug=False):
        super().__init__()
        if controller is None:
            from core.assistant_controller import AssistantController
            controller = AssistantController(skip_preload=skip_preload, debug=debug)
        self.controller = controller
        self.bridge = ControllerBridge()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(4)
        self._command_queue = queue.Queue()
        self._command_thread = threading.Thread(
            target=self._command_loop,
            name="JARVIS-GUI-Commands",
            daemon=True,
        )
        self._command_thread.start()
        self._shutdown_started = False
        self._confirmation_response = threading.Event()
        self._confirmation_pending = threading.Event()
        self._confirmation_decision = "deny"
        self._confirmation_dialog = None
        self.confirmation_timeout_ms = 60000
        self._known_registry = {}
        self._last_speaker_state = "unavailable"
        self._last_task_status = "idle"
        try:
            self.controller.ctx.gui_controller = self
        except Exception:
            pass
        self._wire()

    @Slot(Action)
    def _handle_confirmation_request(self, action: Action):
        """Displays the GUI confirmation dialog for an action."""
        self._confirmation_decision = "deny"
        dialog = QDialog()
        self._confirmation_dialog = dialog
        dialog.setWindowTitle("Action Confirmation Required")
        layout = QVBoxLayout()

        safe_parameters = self.controller.action_manager._redact_sensitive_values(
            action.parameters
        )
        target = safe_parameters.get("target", safe_parameters.get("name", "N/A"))
        layout.addWidget(QLabel(f"<b>Action Name:</b> {action.operation}"))
        layout.addWidget(QLabel(f"<b>Target:</b> {target}"))
        layout.addWidget(QLabel(f"<b>Reason:</b> Approving this action will allow JARVIS to perform a potentially {action.risk_level} operation."))
        layout.addWidget(QLabel(f"<b>Risk Level:</b> <font color='red'>{action.risk_level.upper()}</font>"))

        effect_text = (
            f"Skill: {action.skill}<br>Operation: {action.operation}<br>"
            f"Parameters: {json.dumps(safe_parameters, indent=2)}"
        )
        effect_label = QLabel(f"<b>Exact Effect:</b><br>{effect_text}")
        effect_label.setTextInteractionFlags(Qt.TextSelectableByMouse) # Make text selectable
        layout.addWidget(effect_label)

        # Buttons
        approve_button = QPushButton("Approve Once")
        deny_button = QPushButton("Deny")
        cancel_button = QPushButton("Cancel Task")

        layout.addWidget(approve_button)
        layout.addWidget(deny_button)
        layout.addWidget(cancel_button)
        dialog.setLayout(layout)

        def on_approve():
            self._confirmation_decision = "approve_once"
            dialog.accept()

        def on_deny():
            self._confirmation_decision = "deny"
            dialog.reject()

        def on_cancel():
            self._confirmation_decision = "cancel_task"
            dialog.reject()
        
        approve_button.clicked.connect(on_approve)
        deny_button.clicked.connect(on_deny)
        cancel_button.clicked.connect(on_cancel)

        def timeout():
            if dialog.isVisible():
                self._confirmation_decision = "timeout"
                dialog.reject()

        timeout_timer = QTimer(dialog)
        timeout_timer.setSingleShot(True)
        timeout_timer.timeout.connect(timeout)
        timeout_timer.start(self.confirmation_timeout_ms)

        dialog.exec()
        timeout_timer.stop()
        self._confirmation_dialog = None
        self._confirmation_pending.clear()
        self._confirmation_response.set()
        self.bridge.confirmationResult.emit(self._confirmation_decision)
        dialog.deleteLater()

    def event(self, event):
        if event.type() == CONFIRMATION_EVENT_TYPE:
            self._handle_confirmation_request(event.action)
            return True
        return super().event(event)

    def confirmation_pending(self):
        return self._confirmation_pending.is_set()

    def resolve_confirmation(self, decision):
        if not self.confirmation_pending():
            return False
        if decision is True:
            self._confirmation_decision = "approve_once"
        elif decision is False:
            self._confirmation_decision = "deny"
        else:
            normalized = str(decision).strip().lower()
            self._confirmation_decision = (
                "cancel_task" if normalized in {"cancel", "cancel_task"}
                else "approve_once" if normalized in {"yes", "approve", "approve_once"}
                else "deny"
            )
        dialog = self._confirmation_dialog
        if dialog is not None:
            approved = self._confirmation_decision == "approve_once"
            QTimer.singleShot(0, dialog.accept if approved else dialog.reject)
        self._confirmation_response.set()
        return True


    def _confirmation_handler_from_agent(self, action: Action) -> bool:
        """Receives confirmation request from agent (worker thread) and routes to GUI thread."""
        self._confirmation_decision = "deny"
        self._confirmation_response.clear() # Clear event for new request
        self._confirmation_pending.set()
        self.bridge.confirmationRequested.emit(action)
        QCoreApplication.postEvent(
            self,
            _ConfirmationEvent(action),
            int(Qt.HighEventPriority.value),
        )
        # Block worker thread until GUI thread handles confirmation
        timeout_seconds = max(0.001, self.confirmation_timeout_ms / 1000.0)
        if not self._confirmation_response.wait(timeout=timeout_seconds):
            self._confirmation_pending.clear()
            return "timeout"
        return self._confirmation_decision


    def _wire(self):
        c = self.controller
        b = self.bridge
        c.set_callback("state", self._forward_state)
        c.set_callback("status", self._forward_status)
        c.set_callback("transcription", self._forward_transcription)
        c.set_callback("response", lambda t: b.response.emit(t))
        c.set_callback("timeline", self._forward_timeline)
        c.set_callback("registry", self._forward_registry)
        c.set_callback("log", self._forward_log)
        c.set_callback("wakeword", self._forward_wakeword)
        c.set_callback("voicestate", self._forward_voicestate)
        c.set_callback("agentstatus", self._forward_agentstatus)
        c.set_callback("capabilities", self._forward_capabilities)
        c.set_callback("taskstatus", self._forward_taskstatus)
        c.set_callback("account_connection", self._forward_account_connection)

        # Set the confirmation handler for the DesktopAgent (called from worker thread)
        self.controller.agent.set_confirm_handler(self._confirmation_handler_from_agent)

    def _forward_state(self, state, detail):
        self.bridge.stateChanged.emit(state, detail)
        self.bridge.state_changed.emit(state, detail)
        if str(state).lower() in {"processing", "planning"}:
            self.bridge.planner_state_changed.emit(state, detail)

    def _forward_status(self, value):
        self.bridge.statusChanged.emit(value)
        if not isinstance(value, dict):
            return
        self.bridge.system_metrics_changed.emit(value.get("system_metrics", {}))
        self.bridge.hermes_state_changed.emit(
            str(value.get("hermes", "disabled")),
            str(value.get("hermes_detail", "")),
        )
        self.bridge.browser_state_changed.emit({
            "state": value.get("browser", "unavailable"),
        })
        self.bridge.office_state_changed.emit({
            "word": value.get("word", "unavailable"),
            "excel": value.get("excel", "unavailable"),
            "powerpoint": value.get("powerpoint", "unavailable"),
        })
        self.bridge.research_state_changed.emit({
            "state": value.get("research", "unavailable"),
        })

    def _forward_transcription(self, text):
        self.bridge.transcription.emit(text)
        self.bridge.transcript_changed.emit(text)

    def _forward_timeline(self, stage, text):
        stage = str(stage)
        self.bridge.timeline.emit(stage, text)
        self.bridge.audit_event.emit(stage, text)
        payload = {"stage": stage, "detail": text}
        if stage == "cleaned":
            self.bridge.cleaned_command_changed.emit(text)
        elif stage in {"planned", "planner_step"}:
            self.bridge.planner_state_changed.emit(stage, text)
        elif stage in {"confirmation_requested", "waiting_confirmation"}:
            self.bridge.task_waiting_confirmation.emit(payload)
        elif stage in {"step_started", "executing"}:
            self.bridge.task_step_started.emit(payload)
        elif stage in {"step_completed", "validated"}:
            self.bridge.task_step_completed.emit(payload)
        elif stage in {"step_failed"}:
            self.bridge.task_step_failed.emit(payload)
        elif stage == "completed":
            self.bridge.task_completed.emit(payload)
        elif stage == "cancelled":
            self.bridge.task_cancelled.emit(payload)
        elif stage == "failed":
            self.bridge.task_failed.emit(payload)

    def _forward_registry(self, items):
        items = list(items or [])
        self.bridge.registry.emit(items)
        current = {str(item.get("id")): item for item in items if item.get("id") is not None}
        for entry_id, entry in current.items():
            if entry_id not in self._known_registry:
                self.bridge.application_opened.emit(entry)
        for entry_id, entry in self._known_registry.items():
            if entry_id not in current:
                self.bridge.application_closed.emit(entry)
        self._known_registry = current

    def _forward_log(self, tag, message):
        self.bridge.logLine.emit(tag, message)
        self.bridge.audit_event.emit(tag, message)

    def _forward_wakeword(self, phase):
        self.bridge.wakeword.emit(phase)
        self.bridge.wake_word_state_changed.emit(phase)

    def _forward_voicestate(self, snapshot):
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        self.bridge.voicestate.emit(snapshot)
        self.bridge.voice_state_changed.emit(snapshot)
        try:
            level = float(snapshot.get("input_level", 0.0) or 0.0)
        except (TypeError, ValueError):
            level = 0.0
        self.bridge.microphone_level_changed.emit(level)
        speaker_state = str(snapshot.get("speaker_state", "unavailable"))
        if speaker_state == "speaking" and self._last_speaker_state != "speaking":
            self.bridge.speech_started.emit()
        elif speaker_state != "speaking" and self._last_speaker_state == "speaking":
            self.bridge.speech_finished.emit()
        if speaker_state == "speaking":
            self.bridge.speech_level_changed.emit(level)
        self._last_speaker_state = speaker_state

    def _forward_agentstatus(self, status, detail):
        self.bridge.agentstatus.emit(status, detail)
        if str(status).lower() == "cancelled":
            self.bridge.task_cancelled.emit({"status": status, "detail": detail})

    def _forward_capabilities(self, report):
        self.bridge.capabilities.emit(report)
        self.bridge.capability_status_changed.emit(report)

    def _forward_taskstatus(self, snapshot):
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        self.bridge.taskstatus.emit(snapshot)
        status = str(snapshot.get("status", "idle")).lower()
        if status == "running" and self._last_task_status not in {"running", "paused"}:
            self.bridge.task_started.emit(snapshot)
        self.bridge.task_progress.emit(snapshot)
        if status == "completed":
            self.bridge.task_completed.emit(snapshot)
        elif status == "cancelled":
            self.bridge.task_cancelled.emit(snapshot)
        elif status == "failed":
            self.bridge.task_failed.emit(snapshot)
        self._last_task_status = status

    def _forward_account_connection(self, account, result):
        self.bridge.account_connection_changed.emit(str(account), result)

    # ------------------------------------------------------------------ api
    def run_async(self, fn, *args, **kwargs):
        self.pool.start(_Task(fn, *args, **kwargs))

    def _command_loop(self):
        while True:
            item = self._command_queue.get()
            if item is None:
                return
            fn, args, kwargs, done = item
            try:
                fn(*args, **kwargs)
            except Exception:
                pass
            finally:
                if done is not None:
                    done.set()

    def preload(self):
        self.run_async(self.controller.preload_models)

    def start_voice(self):
        # controller already spawns its own wake thread
        return self.controller.start_voice()

    def stop_voice(self):
        return self.controller.stop_voice()

    def submit_text(self, text):
        if self._is_task_control(text):
            self.pool.start(_Task(self.controller.handle_text, text))
            return
        self._command_queue.put((self.controller.handle_text, (text,), {}, None))

    @staticmethod
    def _is_task_control(text):
        cleaned = str(text or "").strip().lower()
        return re.fullmatch(
            r"(?:pause typing|pause (?:the )?(?:current )?task|"
            r"resume typing|resume (?:the )?(?:current )?task|"
            r"(?:cancel|stop) (?:the )?(?:current )?task|"
            r"(?:write|type) (?:faster|slower))[.! ]*",
            cleaned,
        ) is not None

    def speak(self, text):
        self.run_async(self.controller.speak, text)

    def apply_settings(self):
        return self.controller.apply_settings()

    def begin_account_login(self, account):
        self.run_async(self.controller.begin_account_login, account)

    def verify_account_login(self, account):
        self.run_async(self.controller.verify_account_login, account)

    def status_snapshot(self):
        return self.controller.status_snapshot()

    def registry_items(self):
        return self.controller.registry_items()

    def stop_task(self):
        return self.controller.stop_task()

    @property
    def agent(self):
        return self.controller.agent

    def mute_speech(self):
        self.controller.mute_speech()

    def unmute_speech(self):
        self.controller.unmute_speech()

    def refresh_devices(self):
        return self.controller.refresh_devices()

    def enumerate_devices(self):
        return self.controller.enumerate_devices()

    @property
    def speech_muted(self):
        return self.controller.speech_muted

    def shutdown(self):
        if not self._shutdown_started:
            self._shutdown_started = True
            done = threading.Event()
            self._command_queue.put((self.controller.shutdown, (), {}, done))
            done.wait(timeout=10)
            self._command_queue.put(None)
            self._command_thread.join(timeout=5)
        self.pool.waitForDone(2000)
