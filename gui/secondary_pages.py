"""Operational pages backed by the same state snapshots as the dashboard."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.hud import HudPanel, normalize_state


def _value(text="Unavailable"):
    label = QLabel(str(text))
    label.setObjectName("dataValue")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


class TasksPage(QWidget):
    pauseRequested = Signal()
    resumeRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        active = HudPanel("Active Task")
        self.values = {}
        form = QFormLayout()
        for label, key in (
            ("TASK ID", "task_id"), ("DESCRIPTION", "description"),
            ("APPLICATION", "application"), ("MODE", "mode"),
            ("CURRENT STEP", "step"), ("STATUS", "status"),
        ):
            self.values[key] = _value("Waiting")
            form.addRow(label, self.values[key])
        active.content.addLayout(form)
        self.progress = QProgressBar()
        active.content.addWidget(self.progress)
        controls = QHBoxLayout()
        for text, signal, danger in (
            ("PAUSE", self.pauseRequested, False),
            ("RESUME", self.resumeRequested, False),
            ("CANCEL", self.cancelRequested, True),
        ):
            button = QPushButton(text)
            if danger:
                button.setObjectName("danger")
            button.clicked.connect(signal)
            controls.addWidget(button)
        active.content.addLayout(controls)
        root.addWidget(active, 2)

        history = HudPanel("Task Events")
        self.events = QListWidget()
        history.content.addWidget(self.events, 1)
        root.addWidget(history, 3)

    def set_snapshot(self, snapshot):
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        for key, label in self.values.items():
            value = snapshot.get(key)
            label.setText(normalize_state(value) if key == "status" else str(value or "Waiting"))
        self.progress.setValue(int(snapshot.get("progress") or 0))

    def add_event(self, stage, text):
        self.events.addItem(f"{time.strftime('%H:%M:%S')}  {str(stage).upper()}\n{text}")
        self.events.scrollToBottom()


class MemoryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QGridLayout(self)
        health = HudPanel("Memory Health")
        self.health = _value("Unavailable")
        self.context = _value("Waiting")
        form = QFormLayout()
        form.addRow("STATE", self.health)
        form.addRow("ACTIVE CONTEXT", self.context)
        health.content.addLayout(form)
        root.addWidget(health, 0, 0)
        conversations = HudPanel("Recent Conversations")
        self.conversations = QListWidget()
        conversations.content.addWidget(self.conversations)
        root.addWidget(conversations, 0, 1, 2, 1)
        tasks = HudPanel("Recent Tasks")
        self.tasks = QListWidget()
        tasks.content.addWidget(self.tasks)
        root.addWidget(tasks, 1, 0)

    def set_status(self, snapshot):
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        self.health.setText(normalize_state(snapshot.get("memory", "Unavailable")))
        self.context.setText(snapshot.get("current_task") or "Waiting")

    def add_conversation(self, source, text):
        self.conversations.addItem(f"{time.strftime('%H:%M:%S')}  {source}: {text}")
        while self.conversations.count() > 100:
            self.conversations.takeItem(0)

    def add_task_event(self, stage, text):
        if stage in {"heard", "planned", "executing", "completed", "failed", "cancelled"}:
            self.tasks.addItem(f"{time.strftime('%H:%M:%S')}  {stage.upper()} · {text}")
            while self.tasks.count() > 100:
                self.tasks.takeItem(0)


class ResearchPage(QWidget):
    saveWordRequested = Signal()
    savePdfRequested = Signal()
    newsRefreshRequested = Signal()
    newsReadRequested = Signal()
    newsOpenRequested = Signal()
    newsSaveRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        state = HudPanel("Research State")
        self.values = {}
        form = QFormLayout()
        for label, key in (
            ("TOPIC", "topic"), ("STATE", "status"), ("STAGE", "stage"),
            ("SOURCES FOUND", "sources_found"),
            ("SOURCES ACCEPTED", "sources_verified"),
            ("SOURCES REJECTED", "sources_rejected"),
            ("CITATIONS", "citation_count"),
        ):
            self.values[key] = _value("Unavailable")
            form.addRow(label, self.values[key])
        state.content.addLayout(form)
        controls = QHBoxLayout()
        word = QPushButton("SAVE TO WORD")
        pdf = QPushButton("SAVE TO PDF")
        word.clicked.connect(self.saveWordRequested)
        pdf.clicked.connect(self.savePdfRequested)
        controls.addWidget(word)
        controls.addWidget(pdf)
        state.content.addLayout(controls)
        root.addWidget(state, 2)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(7)
        sources = HudPanel("Verified Sources")
        self.sources = QListWidget()
        sources.content.addWidget(self.sources)
        right_layout.addWidget(sources, 1)
        news = HudPanel("Live News")
        self.news_status = _value("Last refresh: never")
        self.news_list = QListWidget()
        news.content.addWidget(self.news_status)
        news.content.addWidget(self.news_list, 1)
        news_controls = QHBoxLayout()
        for label, signal in (
            ("REFRESH", self.newsRefreshRequested),
            ("READ", self.newsReadRequested),
            ("OPEN", self.newsOpenRequested),
            ("SAVE TO WORD", self.newsSaveRequested),
        ):
            button = QPushButton(label)
            button.clicked.connect(signal)
            news_controls.addWidget(button)
        self.news_refresh_button = news_controls.itemAt(0).widget()
        self.news_read_button = news_controls.itemAt(1).widget()
        self.news_open_button = news_controls.itemAt(2).widget()
        self.news_save_button = news_controls.itemAt(3).widget()
        news.content.addLayout(news_controls)
        right_layout.addWidget(news, 1)
        root.addWidget(right, 3)

    def set_status(self, snapshot):
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        self.values["status"].setText(normalize_state(snapshot.get("research", "Unavailable")))

    def set_task(self, snapshot):
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        metadata = snapshot.get("metadata") or {}
        description = snapshot.get("description") or "Unavailable"
        if "research" in description.lower() or metadata.get("sources_found") is not None:
            self.values["topic"].setText(description)
            self.values["stage"].setText(snapshot.get("step") or "Waiting")
            for key in ("sources_found", "sources_verified", "sources_rejected", "citation_count"):
                self.values[key].setText(str(metadata.get(key, "Unavailable")))


class UniversityAssignmentPage(QWidget):
    """Read-only mission-control view of the authoritative assignment state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        specification = HudPanel("University Assignment")
        self.values = {}
        form = QFormLayout()
        for label, key in (
            ("ASSIGNMENT TYPE", "assignment_type"),
            ("TOPIC", "topic"),
            ("WORD COUNT", "word_count"),
            ("CITATION STYLE", "citation_style"),
            ("ACADEMIC LEVEL", "academic_level"),
            ("CURRENT SECTION", "current_section"),
            ("SOURCE COUNT", "source_count"),
            ("REFERENCE COUNT", "reference_count"),
            ("MILESTONE STAGE", "milestone_stage"),
            ("SAVE STATUS", "save_status"),
        ):
            self.values[key] = _value("Waiting")
            form.addRow(label, self.values[key])
        specification.content.addLayout(form)
        root.addWidget(specification, 3)

        execution = HudPanel("Assignment Progress")
        self.status = _value("Waiting for an assignment request")
        self.progress = QProgressBar()
        execution.content.addWidget(self.status)
        execution.content.addWidget(self.progress)
        execution.content.addStretch(1)
        root.addWidget(execution, 2)

    def set_snapshot(self, snapshot):
        data = snapshot.get("university_assignment", {}) if isinstance(snapshot, dict) else {}
        data = data if isinstance(data, dict) else {}
        for key, label in self.values.items():
            value = data.get(key)
            label.setText(str(value if value not in (None, "") else "Waiting"))
        progress = int(data.get("progress") or 0)
        self.progress.setValue(max(0, min(100, progress)))
        self.status.setText(
            f"{data.get('requested_mode', 'Waiting')} · {progress}%"
            if data else "Waiting for an assignment request"
        )


class AutomationPage(QWidget):
    emergencyStopRequested = Signal()
    closeSelectedRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        state = HudPanel("Desktop Automation")
        self.values = {}
        form = QFormLayout()
        for label, key in (
            ("AGENT", "agent"), ("OPERATION", "operation"),
            ("ACTIVE WINDOW", "window"), ("MOUSE", "mouse"),
            ("KEYBOARD", "keyboard"), ("OWNERSHIP", "ownership"),
        ):
            self.values[key] = _value("Waiting")
            form.addRow(label, self.values[key])
        state.content.addLayout(form)
        stop = QPushButton("EMERGENCY STOP")
        stop.setObjectName("danger")
        stop.clicked.connect(self.emergencyStopRequested)
        state.content.addWidget(stop)
        root.addWidget(state, 2)
        sessions = HudPanel("JARVIS-Owned Sessions")
        self.sessions = QListWidget()
        sessions.content.addWidget(self.sessions)
        root.addWidget(sessions, 3)
        self._raw = []

    def set_agent_status(self, status, detail):
        self.values["agent"].setText(normalize_state(status))
        self.values["operation"].setText(detail or "Waiting")
        active = str(status).lower() in {"moving", "clicking", "typing", "locating"}
        self.values["mouse"].setText("ACTIVE" if active else "WAITING")
        self.values["keyboard"].setText("ACTIVE" if active else "WAITING")

    def set_sessions(self, sessions):
        self._raw = list(sessions or [])
        self.sessions.clear()
        for entry in self._raw:
            name = entry.get("display_name") or entry.get("name") or "Unknown"
            self.sessions.addItem(f"{name} · {entry.get('type', 'item')} · {entry.get('state', 'open')}")
        recent = self._raw[-1] if self._raw else {}
        self.values["window"].setText(recent.get("window_title") or recent.get("name") or "Unavailable")
        self.values["ownership"].setText(
            "JARVIS OWNED" if self._raw else "NO OWNED SESSION"
        )


class LogsPage(QWidget):
    openFolderRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        panel = HudPanel("Live Audit and Runtime Events")
        top = QHBoxLayout()
        self.status = _value("Waiting for events")
        open_button = QPushButton("OPEN LOG FOLDER")
        open_button.clicked.connect(self.openFolderRequested)
        top.addWidget(self.status)
        top.addStretch(1)
        top.addWidget(open_button)
        panel.content.addLayout(top)
        self.events = QListWidget()
        panel.content.addWidget(self.events, 1)
        root.addWidget(panel)

    def add_event(self, tag, message):
        self.status.setText(f"Last event: {tag}")
        self.events.addItem(f"{time.strftime('%H:%M:%S')}  {str(tag).upper()}\n{message}")
        self.events.scrollToBottom()
        while self.events.count() > 500:
            self.events.takeItem(0)


class SettingsPage(QWidget):
    settingsRequested = Signal()
    reducedMotionChanged = Signal(bool)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        root = QHBoxLayout(self)
        overview = HudPanel("Runtime Configuration")
        self.values = {}
        form = QFormLayout()
        for label, key in (
            ("THEME", "theme"), ("MICROPHONE", "microphone_device"),
            ("SPEAKER", "speaker_device"), ("WHISPER", "whisper_model"),
            ("PIPER", "piper_voice"), ("OPENROUTER", "openrouter_model"),
            ("HERMES", "hermes_enabled"), ("BROWSER", "browser_preference"),
            ("SAVE BEHAVIOR", "default_save_behavior"),
            ("CONFIRMATION", "confirmation_policy"), ("LOGS", "logs_folder"),
        ):
            self.values[key] = _value("Unavailable")
            form.addRow(label, self.values[key])
        overview.content.addLayout(form)
        edit = QPushButton("OPEN FULL SETTINGS")
        edit.clicked.connect(self.settingsRequested)
        overview.content.addWidget(edit)
        root.addWidget(overview, 3)
        accessibility = HudPanel("Accessibility and Motion")
        self.reduce_motion = QCheckBox("Reduced motion")
        self.reduce_motion.toggled.connect(self.reducedMotionChanged)
        accessibility.content.addWidget(self.reduce_motion)
        note = _value(
            "Reduced motion slows or suspends nonessential state transitions. "
            "Voice level, progress, confirmation, and fault indicators remain functional."
        )
        accessibility.content.addWidget(note)
        accessibility.content.addStretch(1)
        root.addWidget(accessibility, 2)
        self.refresh()

    def refresh(self):
        data = self.settings.as_dict()
        data.setdefault("theme", "cinematic")
        data.setdefault("default_save_behavior", "Ask")
        data.setdefault("confirmation_policy", "Risk based")
        for key, label in self.values.items():
            if key == "hermes_enabled":
                label.setText("Disabled · not installed" if not data.get(key) else "Enabled")
            else:
                label.setText(str(data.get(key, "Unavailable")))
        self.reduce_motion.blockSignals(True)
        self.reduce_motion.setChecked(bool(data.get("reduce_motion", False)))
        self.reduce_motion.blockSignals(False)
