"""Small HUD building blocks with no backend dependencies."""
from __future__ import annotations

import datetime as _datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


STATE_ALIASES = {
    "ON": "READY",
    "OPEN": "READY",
    "CONNECTED": "READY",
    "WORKING": "READY",
    "IDLE": "READY",
    "EMPTY": "WAITING",
    "CLOSED": "DISCONNECTED",
    "OFF": "DISCONNECTED",
    "REQUIRES CONFIGURATION": "NOT CONFIGURED",
    "REQUIRES_CONFIG": "NOT CONFIGURED",
}


def normalize_state(value) -> str:
    state = str(value or "Unavailable").strip().upper().replace("_", " ")
    return STATE_ALIASES.get(state, state)


class HudPanel(QFrame):
    """Framed panel with a compact technical header and content area."""

    def __init__(self, title: str, parent=None, compact=False):
        super().__init__(parent)
        self.setObjectName("hudPanel")
        self.setProperty("compact", compact)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 9)
        root.setSpacing(6)
        header = QHBoxLayout()
        marker = QLabel("›")
        marker.setObjectName("panelMarker")
        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("panelTitle")
        header.addWidget(marker)
        header.addWidget(self.title_label)
        header.addStretch(1)
        root.addLayout(header)
        self.body = QWidget()
        self.body.setObjectName("panelBody")
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(6)
        root.addWidget(self.body, 1)

    def set_title(self, title: str):
        self.title_label.setText(str(title).upper())


class StatusIndicator(QFrame):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statusIndicator")
        self.setFixedWidth(78)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 5, 6, 5)
        root.setSpacing(5)
        self.dot = QLabel("●")
        self.dot.setObjectName("statusDot")
        labels = QVBoxLayout()
        labels.setSpacing(0)
        self.name_label = QLabel(name.upper())
        self.name_label.setObjectName("statusName")
        self.value_label = QLabel("WAITING")
        self.value_label.setObjectName("statusState")
        labels.addWidget(self.name_label)
        labels.addWidget(self.value_label)
        root.addWidget(self.dot)
        root.addLayout(labels)
        # The widget has not been inserted or painted yet. Re-polishing a
        # complex application stylesheet here once per subsystem makes cold
        # construction scale catastrophically on Windows.
        self.set_state("WAITING", repolish=False)

    def set_state(self, value, repolish=True):
        state = normalize_state(value)
        self.value_label.setText(state)
        state_class = (
            "critical" if state in {"FAILED", "ERROR", "BROKEN"}
            else "warning" if state in {
                "WARNING", "WAITING", "CONNECTING", "TRANSCRIBING",
                "PLANNING", "EXECUTING", "SPEAKING", "NOT CONFIGURED",
                "REQUIRES LOGIN", "DEGRADED",
            }
            else "disabled" if state in {"DISABLED", "DISCONNECTED", "UNAVAILABLE"}
            else "ready"
        )
        self.setProperty("hudState", state_class)
        if repolish:
            self.style().unpolish(self)
            self.style().polish(self)


class SubsystemStatusBar(QScrollArea):
    """Scrollable status rail populated only by controller snapshots."""

    SUBSYSTEMS = (
        ("Voice", "voice"),
        ("Wake Word", "wake"),
        ("Whisper", "whisper"),
        ("OpenRouter", "kimi"),
        ("Hermes", "hermes"),
        ("Desktop Agent", "desktop_agent"),
        ("Browser", "browser"),
        ("Word", "word"),
        ("Excel", "excel"),
        ("PowerPoint", "powerpoint"),
        ("Memory", "memory"),
        ("Research", "research"),
        ("News", "news"),
        ("Settings", "settings"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("subsystemRail")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(64)
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        self.indicators = {}
        for name, key in self.SUBSYSTEMS:
            indicator = StatusIndicator(name)
            self.indicators[key] = indicator
            layout.addWidget(indicator)
        layout.addStretch(1)
        self.setWidget(container)

    def update_snapshot(self, snapshot: dict):
        if not isinstance(snapshot, dict):
            return
        state = normalize_state(snapshot.get("state", "WAITING"))
        voice_state = "LISTENING" if snapshot.get("microphone_active") else (
            "READY" if snapshot.get("microphone_available") else "DISCONNECTED"
        )
        values = {
            "voice": voice_state,
            "wake": "LISTENING" if snapshot.get("wakeword_active") else (
                "READY" if snapshot.get("wakeword_loaded") else "DISCONNECTED"
            ),
            "whisper": "READY" if snapshot.get("whisper_loaded") else "WAITING",
            "kimi": snapshot.get("kimi", "NOT CONFIGURED"),
            "hermes": snapshot.get("hermes", "DISABLED"),
            "desktop_agent": snapshot.get("desktop_agent", "UNAVAILABLE"),
            "browser": snapshot.get("browser", "DISCONNECTED"),
            "word": snapshot.get("word", "DISCONNECTED"),
            "excel": snapshot.get("excel", "DISCONNECTED"),
            "powerpoint": snapshot.get("powerpoint", "DISCONNECTED"),
            "memory": snapshot.get("memory", "UNAVAILABLE"),
            "research": snapshot.get("research", "WAITING"),
            "news": snapshot.get("news", "WAITING"),
            "settings": snapshot.get("settings", "READY"),
        }
        if state in {"LISTENING WAKE", "RECORDING", "PROCESSING", "SPEAKING"}:
            values["voice"] = {
                "LISTENING WAKE": "LISTENING",
                "RECORDING": "LISTENING",
                "PROCESSING": "TRANSCRIBING",
                "SPEAKING": "SPEAKING",
            }[state]
        for key, value in values.items():
            self.indicators[key].set_state(value)

    def update_sessions(self, sessions):
        text = " ".join(
            f"{item.get('name', '')} {item.get('window_title', '')}".lower()
            for item in sessions or []
        )
        self.indicators["word"].set_state("READY" if "word" in text else "DISCONNECTED")
        self.indicators["excel"].set_state("READY" if "excel" in text else "DISCONNECTED")
        has_powerpoint = "powerpoint" in text or "powerpnt" in text
        self.indicators["powerpoint"].set_state("READY" if has_powerpoint else "DISCONNECTED")


class DigitalClock(HudPanel):
    def __init__(self, parent=None):
        super().__init__("Local Time", parent, compact=True)
        self.time_label = QLabel()
        self.time_label.setObjectName("clockTime")
        self.date_label = QLabel()
        self.date_label.setObjectName("clockDate")
        self.content.addWidget(self.time_label, alignment=Qt.AlignCenter)
        self.content.addWidget(self.date_label, alignment=Qt.AlignCenter)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)
        self._refresh()

    def _refresh(self):
        now = _datetime.datetime.now().astimezone()
        self.time_label.setText(now.strftime("%H:%M:%S"))
        self.date_label.setText(now.strftime("%A · %d %B %Y · %Z"))
