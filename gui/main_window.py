"""Cinematic JARVIS desktop shell connected exclusively through Qt signals."""
from __future__ import annotations

import json
import os
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui import styles
from gui.capabilities_page import CapabilitiesPage
from gui.dashboard_page import DashboardPage
from gui.secondary_pages import (
    AutomationPage,
    LogsPage,
    MemoryPage,
    ResearchPage,
    SettingsPage,
    TasksPage,
    UniversityAssignmentPage,
)


NAVIGATION = (
    ("Dashboard", "dashboard"),
    ("Capabilities", "capabilities"),
    ("Tasks", "tasks"),
    ("Memory", "memory"),
    ("Research", "research"),
    ("University", "university"),
    ("Automation", "automation"),
    ("Logs", "logs"),
    ("Settings", "settings"),
)


class MainWindow(QWidget):
    """Responsive presentation layer; all work stays in backend services."""

    exitRequested = Signal()
    minimizeRequested = Signal()
    settingsRequested = Signal()
    autoVoiceReady = Signal(bool)

    def __init__(self, gui_controller, settings, startup_progress=None):
        super().__init__()
        self.gc = gui_controller
        self.settings = settings
        self._startup_progress = startup_progress
        self._voice_on = False
        self._last_speaker_state = "unavailable"
        self._latest_status = {}
        self._latest_task = {}
        self._latest_registry = []
        self._action_nodes = []
        self._build_ui()
        self._wire_signals()
        self._command_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        self._command_shortcut.activated.connect(self._focus_command_input)
        self._refresh_registry()
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._refresh_status)
        self._poll.timeout.connect(self._refresh_registry)
        self._poll.start(1500)

    def _report_startup(self, message):
        if callable(self._startup_progress):
            self._startup_progress(str(message))
        app = QApplication.instance()
        if app is not None:
            app.processEvents()

    def _build_ui(self):
        self.setObjectName("windowRoot")
        self.setWindowTitle("JARVIS · Desktop Intelligence System")
        self.resize(1680, 940)
        self.setMinimumSize(1180, 700)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 7, 8, 7)
        root.setSpacing(6)

        top = QFrame()
        top.setObjectName("topFrame")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(13, 6, 8, 6)
        top_layout.setSpacing(8)
        title_block = QVBoxLayout()
        title_block.setSpacing(0)
        self.title = QLabel("J A R V I S")
        self.title.setObjectName("title")
        self.subtitle = QLabel("DESKTOP INTELLIGENCE · VERIFIED SOURCE MODE")
        self.subtitle.setObjectName("subtitle")
        title_block.addWidget(self.title)
        title_block.addWidget(self.subtitle)
        top_layout.addLayout(title_block)
        top_layout.addStretch(1)
        self.current_status = QLabel("Status: starting")
        self.current_status.setObjectName("dataValue")
        top_layout.addWidget(self.current_status)
        self.status_chip = QLabel("STARTING")
        self.status_chip.setObjectName("statusChip")
        top_layout.addWidget(self.status_chip)
        self.btn_min = QPushButton("—")
        self.btn_min.setFixedWidth(36)
        self.btn_min.setToolTip("Minimize to tray")
        self.btn_min.clicked.connect(self._on_minimize)
        self.btn_exit = QPushButton("×")
        self.btn_exit.setObjectName("danger")
        self.btn_exit.setFixedWidth(36)
        self.btn_exit.setToolTip("Exit JARVIS")
        self.btn_exit.clicked.connect(self._on_exit)
        top_layout.addWidget(self.btn_min)
        top_layout.addWidget(self.btn_exit)
        root.addWidget(top)
        self._report_startup("Building subsystem status")

        from gui.widgets.hud import SubsystemStatusBar
        self.subsystems = SubsystemStatusBar()
        root.addWidget(self.subsystems)
        self._report_startup("Building mission-control dashboard")

        reduced = bool(self.settings.get("reduce_motion", False))
        self.pages = QStackedWidget()
        self.dashboard = DashboardPage(reduced_motion=reduced)
        self._report_startup("Building capability controls")
        self.capabilities_page = CapabilitiesPage(self.gc)
        self._report_startup("Building task and memory controls")
        self.tasks_page = TasksPage()
        self.memory_page = MemoryPage()
        self._report_startup("Building research and automation controls")
        self.research_page = ResearchPage()
        self.university_page = UniversityAssignmentPage()
        self.automation_page = AutomationPage()
        self._report_startup("Building logs and settings")
        self.logs_page = LogsPage()
        self.settings_page = SettingsPage(self.settings)
        self.page_map = {
            "dashboard": self.dashboard,
            "capabilities": self.capabilities_page,
            "tasks": self.tasks_page,
            "memory": self.memory_page,
            "research": self.research_page,
            "university": self.university_page,
            "automation": self.automation_page,
            "logs": self.logs_page,
            "settings": self.settings_page,
        }
        for _label, key in NAVIGATION:
            self.pages.addWidget(self.page_map[key])
        root.addWidget(self.pages, 1)

        nav = QHBoxLayout()
        nav.setSpacing(4)
        nav.addStretch(1)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        for index, (label, key) in enumerate(NAVIGATION):
            button = QPushButton(label.upper())
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, page=key: self._show_page(page))
            self.nav_group.addButton(button, index)
            self.nav_buttons[key] = button
            nav.addWidget(button)
        nav.addStretch(1)
        root.addLayout(nav)
        self.creator_credit = QLabel("MADE BY BURABEEH")
        self.creator_credit.setObjectName("creatorCredit")
        self.creator_credit.setAlignment(Qt.AlignCenter)
        root.addWidget(self.creator_credit)
        self.nav_buttons["dashboard"].setChecked(True)

        self._install_compatibility_aliases()
        self._wire_page_actions()

    def _install_compatibility_aliases(self):
        quick = self.dashboard.quick_actions.buttons
        self.core = self.dashboard.core
        self.input = self.dashboard.conversation.input
        self.btn_send = self.dashboard.conversation.send_button
        self.btn_start = quick["start_voice"]
        self.btn_stop = quick["stop_voice"]
        self.btn_mute = quick["mute_speech"]
        self.btn_mute.setCheckable(True)
        self.btn_browser = quick["open_browser"]
        self.btn_files = quick["open_folder"]
        self.btn_logs = quick["logs"]
        self.btn_settings = quick["settings"]
        self.btn_stoptask = quick["stop_task"]
        self.btn_pause_task = self.dashboard.task.pause_button
        self.btn_resume_task = self.dashboard.task.resume_button
        self.btn_cancel_task = self.dashboard.task.cancel_button
        self.task_progress = self.dashboard.task.progress
        self.activity = self.dashboard.conversation.messages
        self.apps = self.dashboard.applications.items
        self.timeline = self.dashboard.timeline.events
        self.skill_status = QLabel("Ready")
        self.news_list = self.research_page.news_list
        self.news_refresh_lbl = self.research_page.news_status
        self.btn_news_refresh = self.research_page.news_refresh_button
        self.btn_news_read = self.research_page.news_read_button
        self.btn_news_open = self.research_page.news_open_button
        self.btn_news_save = self.research_page.news_save_button
        self.fields = {
            "transcription": self.dashboard.conversation.current_transcript,
            "cleaned": self.dashboard.conversation.cleaned_command,
            "action": self.dashboard.reasoning.values["step"],
            "skill": self.dashboard.reasoning.values["capability"],
            "response": QLabel("Waiting"),
            "task": self.dashboard.task.values["description"],
            "app": self.dashboard.task.values.get("application", QLabel("Waiting")),
            "sessions": QLabel("0"),
            "mode": self.dashboard.task.values["mode"],
            "step": self.dashboard.task.values["step"],
        }
        self.telemetry = {
            "mic": self.subsystems.indicators["voice"].value_label,
            "wake": self.subsystems.indicators["wake"].value_label,
            "whisper": self.subsystems.indicators["whisper"].value_label,
            "piper": self.subsystems.indicators["voice"].value_label,
            "kimi": self.subsystems.indicators["kimi"].value_label,
            "hermes": self.subsystems.indicators["hermes"].value_label,
            "desktop_agent": self.subsystems.indicators["desktop_agent"].value_label,
            "browser": self.subsystems.indicators["browser"].value_label,
            "word": self.subsystems.indicators["word"].value_label,
            "excel": self.subsystems.indicators["excel"].value_label,
            "memory": self.subsystems.indicators["memory"].value_label,
            "research": self.subsystems.indicators["research"].value_label,
            "news": self.subsystems.indicators["news"].value_label,
            "state": self.status_chip,
        }
        self.system_fields = {key: QLabel("Unavailable") for key in (
            "cpu_percent", "ram_percent", "disk_percent", "temperature_c",
            "gpu_percent", "vram_percent", "network_sent_bytes",
            "network_received_bytes", "python_threads",
        )}

    def _wire_page_actions(self):
        self.dashboard.commandSubmitted.connect(self._quick)
        self.dashboard.quickActionRequested.connect(self._handle_quick_action)
        self.dashboard.pauseRequested.connect(lambda: self._quick("pause the current task"))
        self.dashboard.resumeRequested.connect(lambda: self._quick("resume the current task"))
        self.dashboard.cancelRequested.connect(self._on_stop_task)
        self.dashboard.capabilityPageRequested.connect(lambda: self._show_page("capabilities"))
        self.dashboard.closeApplicationRequested.connect(self._close_named)
        self.dashboard.focusApplicationRequested.connect(self._focus_named)
        self.dashboard.closeAllRequested.connect(self._on_close_all)
        self.dashboard.hermesApproveRequested.connect(
            lambda task_id: self._quick(f"approve Hermes task {task_id}")
        )
        self.dashboard.hermesDenyRequested.connect(
            lambda task_id: self._quick(f"deny Hermes task {task_id}")
        )
        self.dashboard.hermesCancelRequested.connect(
            lambda task_id: self._quick(f"cancel Hermes task {task_id}")
        )
        self.tasks_page.pauseRequested.connect(lambda: self._quick("pause the current task"))
        self.tasks_page.resumeRequested.connect(lambda: self._quick("resume the current task"))
        self.tasks_page.cancelRequested.connect(self._on_stop_task)
        self.automation_page.emergencyStopRequested.connect(self._on_emergency_stop)
        self.logs_page.openFolderRequested.connect(self._on_logs)
        self.settings_page.settingsRequested.connect(self._on_settings)
        self.settings_page.reducedMotionChanged.connect(self._set_reduced_motion)
        self.research_page.saveWordRequested.connect(lambda: self._quick("save the research to Word"))
        self.research_page.savePdfRequested.connect(lambda: self._quick("save the research to PDF"))
        self.research_page.newsRefreshRequested.connect(self._skill_news_refresh)
        self.research_page.newsReadRequested.connect(self._skill_news_read)
        self.research_page.newsOpenRequested.connect(self._skill_news_open)
        self.research_page.newsSaveRequested.connect(self._skill_news_save)

    def _wire_signals(self):
        bridge = self.gc.bridge
        bridge.stateChanged.connect(self._slot_state)
        bridge.statusChanged.connect(self._slot_status)
        bridge.transcription.connect(self._slot_transcription)
        bridge.response.connect(self._slot_response)
        bridge.timeline.connect(self._slot_timeline)
        bridge.registry.connect(self._fill_registry)
        bridge.logLine.connect(self._slot_log)
        bridge.wakeword.connect(self._slot_wakeword)
        bridge.voicestate.connect(self._slot_voicestate)
        bridge.agentstatus.connect(self._slot_agentstatus)
        bridge.capabilities.connect(self._slot_capabilities)
        bridge.taskstatus.connect(self._slot_taskstatus)
        bridge.confirmationRequested.connect(self._slot_confirmation_requested)
        bridge.confirmationResult.connect(self._slot_confirmation_result)
        bridge.news_items_changed.connect(self._fill_news)

    def _show_page(self, key):
        widget = self.page_map.get(key)
        if widget is None:
            return
        self.pages.setCurrentWidget(widget)
        if key in self.nav_buttons:
            self.nav_buttons[key].setChecked(True)
        if key == "settings":
            self.settings_page.refresh()

    def _slot_state(self, state, detail):
        pretty = str(state or "waiting").replace("_", " ")
        self.dashboard.set_state(state, detail)
        self.current_status.setText(f"Status: {pretty}" + (f" · {detail}" if detail else ""))
        self.status_chip.setText(pretty.upper())
        if state in {"recording", "wake_detected"}:
            self.core.trigger_pulse()

    def _slot_status(self, value):
        if not isinstance(value, dict):
            self.current_status.setText(f"Status: {value}")
            return
        snapshot = dict(value)
        snapshot["settings"] = "ready"
        self._latest_status = snapshot
        self.subsystems.update_snapshot(snapshot)
        self.dashboard.workspace.set_snapshot(snapshot)
        self.dashboard.hermes.set_snapshot(snapshot)
        self.memory_page.set_status(snapshot)
        self.research_page.set_status(snapshot)
        self.university_page.set_snapshot(snapshot)
        self.fields["sessions"].setText(str(snapshot.get("sessions", 0)))
        if snapshot.get("last_response"):
            self.fields["response"].setText(str(snapshot["last_response"]))
        if snapshot.get("current_task"):
            self.fields["task"].setText(str(snapshot["current_task"]))
        metrics = snapshot.get("system_metrics", {})
        self.dashboard.metrics.set_metrics(metrics)
        if isinstance(metrics, dict):
            for key, label in self.system_fields.items():
                metric = metrics.get(key)
                label.setText("Unavailable" if metric is None else str(metric))

    def _slot_transcription(self, text):
        self.dashboard.conversation.set_transcript(text)

    def _slot_response(self, text):
        self.fields["response"].setText(str(text))
        self._log_activity("JARVIS", text, "assistant")

    def _slot_timeline(self, stage, text):
        stage = str(stage)
        text = str(text)
        self.dashboard.timeline.add_event(stage, text)
        self.tasks_page.add_event(stage, text)
        self.memory_page.add_task_event(stage, text)
        if stage == "cleaned":
            self.dashboard.conversation.set_cleaned(text)
            self.dashboard.reasoning.begin_goal(text)
        elif stage in {"planned", "planner_step"}:
            self.dashboard.reasoning.set_planner(
                "OpenRouter Safety" if "safeguard" in text.lower() else "Backend planner"
            )
            self.dashboard.reasoning.set_step(text)
        elif stage in {
            "validated", "executing", "confirmation_requested", "confirmation_result",
            "step_started", "step_completed", "step_failed", "retry", "rollback",
        }:
            if (
                stage == "validated"
                and self.dashboard.reasoning.values["planner"].text()
                in {"Waiting", "Unavailable"}
            ):
                self.dashboard.reasoning.set_planner("Deterministic router")
            self._apply_structured_timeline(stage, text)
        elif stage == "completed":
            self.dashboard.reasoning.set_step("Completed")
            self.dashboard.reasoning.set_recovery("Not required")
        elif stage == "cancelled":
            self.dashboard.reasoning.set_step("Cancelled")
            self.dashboard.reasoning.set_recovery("Cancelled safely")
        elif stage == "failed":
            self.dashboard.reasoning.set_step("Failed")
        if stage in {"failed", "step_failed"}:
            self.dashboard.reasoning.set_recovery("Failure reported by backend")
        elif stage in {"retry", "rollback"}:
            self.dashboard.reasoning.set_recovery(stage.replace("_", " ").title())
        label = stage.replace("_", " ").title()
        if label not in self._action_nodes:
            self._action_nodes.append(label)
            self._action_nodes = self._action_nodes[-5:]
            self.core.set_action_nodes(self._action_nodes)

    def _apply_structured_timeline(self, stage, text):
        try:
            payload = json.loads(text)
            action = payload.get("action", payload)
            skill = action.get("skill", "")
            operation = action.get("operation", "")
            capability = f"{skill}.{operation}".strip(".")
            self.fields["action"].setText(capability or text)
            self.fields["skill"].setText(skill or "Unavailable")
            self.dashboard.reasoning.set_capability(capability)
            self.dashboard.reasoning.set_step(stage.replace("_", " ").title())
        except (TypeError, ValueError, AttributeError):
            self.fields["action"].setText(text)
            self.dashboard.reasoning.set_step(text)

    def _slot_log(self, tag, msg):
        self.logs_page.add_event(tag, msg)
        self._log_activity(tag, msg, "runtime")

    def _slot_wakeword(self, phase):
        state = "LISTENING" if phase == "ready" else "READY" if phase == "detected" else phase
        self.subsystems.indicators["wake"].set_state(state)

    def _slot_voicestate(self, snapshot):
        if not isinstance(snapshot, dict):
            return
        self._voice_on = bool(snapshot.get("microphone_active"))
        self.dashboard.set_voice_snapshot(snapshot)
        self.subsystems.update_snapshot({**self._latest_status, **snapshot})
        previous_speaker = self._last_speaker_state
        speaker = str(snapshot.get("speaker_state", "unavailable"))
        self._last_speaker_state = speaker
        if snapshot.get("conversation_interrupted"):
            self.dashboard.set_state("interrupted", "Conversation interrupted")
        elif snapshot.get("waiting_for_reply"):
            self.dashboard.set_state("conversation_listening", "Waiting for your reply")
        elif snapshot.get("conversation_active") and snapshot.get("processing"):
            self.dashboard.set_state("thinking", "Conversation active")
        elif speaker == "speaking":
            self.dashboard.set_state("speaking", "Piper output active")
        elif previous_speaker == "speaking":
            if snapshot.get("recording"):
                self.dashboard.set_state("recording", "Recording command")
            elif snapshot.get("processing"):
                self.dashboard.set_state("processing", "Processing voice command")
            elif snapshot.get("conversation_active"):
                self.dashboard.set_state("conversation_listening", "Waiting for your reply")
            elif snapshot.get("microphone_active") and snapshot.get("wakeword_active"):
                self.dashboard.set_state("listening_wake", "Waiting for Hey Jarvis")
            elif speaker == "error":
                self.dashboard.set_state("error", "Piper output error")
            else:
                detail = "Piper muted" if speaker == "muted" else "Ready for command"
                self.dashboard.set_state("ready", detail)
        error = snapshot.get("last_audio_error")
        if error:
            self.current_status.setText(f"Audio error: {error}")

    def _slot_agentstatus(self, status, detail):
        self.fields["action"].setText(f"{status}: {detail}")
        self.status_chip.setText(str(status).upper())
        self.automation_page.set_agent_status(status, detail)
        state = "error" if str(status).lower() == "failed" else "executing"
        if str(status).lower() in {"completed", "cancelled"}:
            state = str(status).lower()
        self.dashboard.set_state(state, detail)

    def _slot_capabilities(self, report):
        self.capabilities_page.set_report(report)
        self.dashboard.capabilities.set_report(report)

    def _slot_taskstatus(self, snapshot):
        if not isinstance(snapshot, dict):
            return
        self._latest_task = dict(snapshot)
        self.dashboard.task.set_snapshot(snapshot)
        self.tasks_page.set_snapshot(snapshot)
        self.research_page.set_task(snapshot)
        self.fields["task"].setText(snapshot.get("description") or "Waiting")
        self.fields["app"].setText(snapshot.get("application") or "Waiting")
        self.fields["mode"].setText(snapshot.get("mode") or "Waiting")
        self.fields["step"].setText(snapshot.get("step") or "Waiting")
        status = str(snapshot.get("status", "idle")).lower()
        state = {
            "running": "executing", "paused": "waiting_confirmation",
            "failed": "failed", "cancelled": "cancelled", "completed": "ready",
        }.get(status, "idle")
        self.dashboard.set_state(state, snapshot.get("step") or status)

    def _slot_confirmation_requested(self, action):
        operation = getattr(action, "operation", "action")
        self.dashboard.set_state("waiting_confirmation", f"Confirmation required: {operation}")

    def _slot_confirmation_result(self, decision):
        self.dashboard.set_state("ready", f"Confirmation result: {decision}")

    def _log_activity(self, source, text, origin="typed"):
        self.dashboard.conversation.add_message(source, text, origin)
        self.memory_page.add_conversation(source, text)

    def _refresh_status(self):
        try:
            refresh_async = getattr(self.gc, "refresh_status_async", None)
            if callable(refresh_async):
                refresh_async()
            else:
                # Compatibility for lightweight presentation-test doubles.
                self._slot_status(self.gc.status_snapshot())
        except Exception as exc:
            self.current_status.setText(f"Status unavailable: {exc}")

    def _refresh_registry(self):
        try:
            self._fill_registry(self.gc.registry_items())
        except Exception:
            self._fill_registry([])

    def _fill_registry(self, items):
        self._latest_registry = list(items or [])
        self.dashboard.applications.set_items(self._latest_registry)
        self.automation_page.set_sessions(self._latest_registry)
        self.subsystems.update_sessions(self._latest_registry)
        self.fields["sessions"].setText(str(len(self._latest_registry)))

    def _quick(self, text):
        text = str(text).strip()
        if not text:
            return
        self._log_activity("YOU", text, "typed")
        self.gc.submit_text(text)

    def _focus_command_input(self):
        self._show_page("dashboard")
        self.input.setFocus(Qt.ShortcutFocusReason)
        self.input.selectAll()

    def _on_send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._quick(text)

    def _handle_quick_action(self, action):
        handlers = {
            "start_voice": self._on_start_voice,
            "stop_voice": self._on_stop_voice,
            "mute_speech": lambda: self._on_mute(self.btn_mute.isChecked()),
            "open_browser": lambda: self._quick("open the browser"),
            "open_application": self._prompt_open_application,
            "open_folder": self._prompt_open_folder,
            "screenshot": self._skill_screenshot,
            "selftest": lambda: self._quick("/selftest"),
            "capabilities": lambda: self._show_page("capabilities"),
            "logs": self._on_logs,
            "settings": self._on_settings,
            "stop_task": self._on_stop_task,
            "emergency_stop": self._on_emergency_stop,
        }
        handler = handlers.get(action)
        if handler:
            handler()

    def _prompt_open_application(self):
        name, accepted = QInputDialog.getText(self, "Open Application", "Application name:")
        if accepted and name.strip():
            self._quick(f"open {name.strip()}")

    def _prompt_open_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Open Folder")
        if path:
            self._quick(f'open folder "{path}"')

    def _on_start_voice(self):
        if self._voice_on:
            return
        if self.gc.start_voice():
            self._voice_on = True
            self._log_activity("VOICE", "Start requested", "control")

    def _on_auto_voice_started(self, started):
        self._voice_on = bool(started)
        detail = "Listening for Hey Jarvis" if started else "Automatic start failed"
        self._log_activity("VOICE", detail, "control" if started else "error")
        self.autoVoiceReady.emit(bool(started))

    def _on_stop_voice(self):
        if self.gc.stop_voice():
            self._voice_on = False
            self._log_activity("VOICE", "Stop requested", "control")

    def _on_mute(self, checked):
        if checked:
            self.gc.mute_speech()
        else:
            self.gc.unmute_speech()
        self.btn_mute.setText("UNMUTE SPEECH" if checked else "MUTE SPEECH")

    def _on_stop_task(self):
        self.gc.stop_task()
        self._log_activity("AGENT", "Stop task requested", "control")

    def _on_emergency_stop(self):
        # Use the same pre-emptive command path as typed and voice requests.
        # That path stops Piper, active automation, browser work, Hermes, and
        # pending commands instead of giving the GUI button a weaker meaning.
        self._quick("emergency stop")
        try:
            self.gc.bridge.emergency_stop_triggered.emit()
        except AttributeError:
            pass
        self.dashboard.set_state("cancelled", "Emergency stop requested")
        self.logs_page.add_event("emergency", "Emergency stop requested by user")

    def _set_reduced_motion(self, enabled):
        self.settings.set("reduce_motion", bool(enabled))
        self.settings.save()
        self.dashboard.set_reduce_motion(enabled)

    def _run_skill(self, text):
        self.skill_status.setText(f"Running: {text}")
        self._quick(text)

    def _skill_screenshot(self):
        self.skill_status.setText("Capturing active desktop state…")

        def work():
            try:
                result = self.gc.controller.agent.screenshot()
                self.gc.bridge.logLine.emit("screenshot", str(result))
            except Exception as exc:
                self.gc.bridge.logLine.emit("screenshot", f"Failed: {exc}")

        self.gc.run_async(work)

    def _skill_read_screen(self):
        self.gc.run_async(
            lambda: self.gc.bridge.logLine.emit(
                "screen", self.gc.controller.agent.active_window_title() or "Unavailable"
            )
        )

    def _skill_test_openrouter(self):
        def work():
            try:
                ok, model, detail = self.gc.controller.ctx.llm.test_connection()
                result = f"{'Connected' if ok else 'Failed'} · {model}: {detail}"
            except Exception as exc:
                result = f"OpenRouter test failed: {exc}"
            self.gc.bridge.logLine.emit("openrouter", result)

        self.gc.run_async(work)

    def _news_service(self):
        from skills.news_service import NewsService
        service = getattr(self, "_news_svc", None)
        if service is None:
            service = NewsService(self.gc.controller.ctx)
            self._news_svc = service
        return service

    def _skill_news_refresh(self):
        self.news_refresh_lbl.setText("Refreshing real news feeds…")

        def work():
            try:
                items = self._news_service().headlines("top", limit=10)
                self.gc.bridge.news_items_changed.emit(items)
                self.gc.bridge.logLine.emit("news", f"{len(items)} headlines loaded")
            except Exception as exc:
                self.gc.bridge.logLine.emit("news", f"Refresh failed: {exc}")

        self.gc.run_async(work)

    def _fill_news(self, items):
        self.news_list.clear()
        for item in items or []:
            self.news_list.addItem(f"{item.get('title', 'Untitled')} · {item.get('source', 'Unknown')}")
        try:
            refreshed = self._news_service().last_refresh_str()
        except Exception:
            refreshed = "Unavailable"
        self.news_refresh_lbl.setText(f"Last refresh: {refreshed}")

    def _skill_news_read(self):
        row = max(0, self.news_list.currentRow())
        self.gc.run_async(self._news_service().read_headline, row)

    def _skill_news_open(self):
        row = self.news_list.currentRow()
        items = self._news_service().cached()
        if 0 <= row < len(items) and items[row].get("link"):
            self._quick(f"open {items[row]['link']}")

    def _skill_news_save(self):
        self._quick("save the news to Word")

    def _on_logs(self):
        path = self.settings.get("logs_folder")
        try:
            os.startfile(str(path))
        except Exception as exc:
            self.logs_page.add_event("error", f"Open logs failed: {exc}")

    def _on_settings(self):
        self.settingsRequested.emit()

    def _on_minimize(self):
        self.minimizeRequested.emit()

    def _on_exit(self):
        self.exitRequested.emit()

    def prepare_shutdown(self):
        """Stop every presentation timer before backend teardown begins."""
        self._poll.stop()
        for timer in self.findChildren(QTimer):
            timer.stop()

    def _selected_name(self):
        return self.dashboard.applications.selected_name()

    def _close_named(self, name):
        if name:
            self._quick(f"close {name}")

    def _focus_named(self, name):
        if name:
            self._quick(f"bring {name} to the front")

    def _on_close_selected(self):
        self._close_named(self._selected_name())

    def _on_bring_front(self):
        self._focus_named(self._selected_name())

    def _on_close_all(self):
        self._quick("close everything you opened")

    def closeEvent(self, event):
        self.prepare_shutdown()
        super().closeEvent(event)
