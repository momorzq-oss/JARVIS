"""State-only dashboard panels used by the cinematic JARVIS layout."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui import styles
from gui.widgets.hud import HudPanel, normalize_state


def _value_label(text="Unavailable"):
    label = QLabel(str(text))
    label.setObjectName("dataValue")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


class WaveformWidget(QWidget):
    """Low-cost waveform driven only by supplied microphone/speech levels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(58)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._level = 0.0
        self._phase = 0.0
        self._active = False
        self._reduce_motion = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_level(self, level):
        try:
            self._level = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            self._level = 0.0
        self._active = self._level > 0.003
        if self._active:
            self._timer.start(250 if self._reduce_motion else 40)
        else:
            self._timer.stop()
        self.update()

    def set_reduce_motion(self, enabled):
        self._reduce_motion = bool(enabled)
        self.set_level(self._level)

    def _tick(self):
        if not self._reduce_motion and self._active:
            self._phase += 0.22
        else:
            self._level *= 0.88
            if self._level < 0.003:
                self._active = False
                self._timer.stop()
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = self.height() / 2
        quiet = QColor(styles.CYAN_DIM)
        quiet.setAlpha(90)
        painter.setPen(QPen(quiet, 1))
        painter.drawLine(0, int(center), self.width(), int(center))
        active = QColor(styles.CYAN_GLOW)
        active.setAlpha(220 if self._active else 80)
        painter.setPen(QPen(active, 1.5))
        points = []
        samples = max(32, self.width() // 5)
        amplitude = max(1.5, self._level * self.height() * 0.42)
        for index in range(samples):
            x = index * self.width() / max(1, samples - 1)
            envelope = math.sin(math.pi * index / max(1, samples - 1))
            signal = math.sin(self._phase + index * 0.72) * math.sin(index * 0.19)
            y = center + signal * amplitude * envelope
            points.append((int(x), int(y)))
        for first, second in zip(points, points[1:]):
            painter.drawLine(first[0], first[1], second[0], second[1])
        painter.end()


class CircularGauge(QWidget):
    def __init__(self, label, parent=None):
        super().__init__(parent)
        self.label = str(label)
        self.value = None
        self.setMinimumSize(82, 82)

    def set_value(self, value):
        try:
            self.value = max(0.0, min(100.0, float(value))) if value is not None else None
        except (TypeError, ValueError):
            self.value = None
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        rect = QRectF((self.width() - side) / 2 + 7, 7, side - 14, side - 14)
        painter.setBrush(Qt.NoBrush)
        base_pen = QPen(QColor(23, 55, 68, 180), 5)
        base_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(base_pen)
        painter.drawArc(rect, 35 * 16, 290 * 16)
        if self.value is not None:
            color = styles.DANGER if self.value >= 90 else styles.AMBER if self.value >= 75 else styles.CYAN
            value_pen = QPen(QColor(color), 5)
            value_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(value_pen)
            painter.drawArc(rect, 35 * 16, int(290 * 16 * self.value / 100))
        painter.setPen(QColor(styles.TEXT))
        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        text = "N/A" if self.value is None else f"{self.value:.0f}%"
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.setPen(QColor(styles.TEXT_DIM))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(QRectF(rect.left(), rect.bottom() - 12, rect.width(), 14), Qt.AlignCenter, self.label.upper())
        painter.end()


class ConversationPanel(HudPanel):
    commandSubmitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__("Conversation", parent)
        self.current_transcript = _value_label("Waiting for voice input")
        self.cleaned_command = _value_label("Waiting for command")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(3)
        form.addRow("VOICE", self.current_transcript)
        form.addRow("CLEAN", self.cleaned_command)
        self.content.addLayout(form)
        self.messages = QListWidget()
        self.messages.setObjectName("conversationList")
        self.messages.setMinimumHeight(126)
        self.content.addWidget(self.messages, 1)
        command = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a command…")
        self.input.returnPressed.connect(self._submit)
        self.send_button = QPushButton("SEND")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self._submit)
        command.addWidget(self.input, 1)
        command.addWidget(self.send_button)
        self.content.addLayout(command)

    def _submit(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.commandSubmitted.emit(text)

    def set_transcript(self, text):
        self.current_transcript.setText(str(text or "Waiting for voice input"))

    def set_cleaned(self, text):
        self.cleaned_command.setText(str(text or "Waiting for command"))

    def add_message(self, source, text, origin="system"):
        timestamp = time.strftime("%H:%M:%S")
        source_text = str(source).upper()
        item = QListWidgetItem(f"{timestamp}  {source_text} · {origin}\n{text}")
        self.messages.addItem(item)
        self.messages.scrollToBottom()
        while self.messages.count() > 200:
            self.messages.takeItem(0)


class VoicePanel(HudPanel):
    def __init__(self, parent=None):
        super().__init__("Voice Link", parent, compact=True)
        self.state_label = _value_label("Disconnected")
        self.device_label = _value_label("Unavailable")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(2)
        form.addRow("STATE", self.state_label)
        form.addRow("INPUT", self.device_label)
        self.content.addLayout(form)
        self.waveform = WaveformWidget()
        self.content.addWidget(self.waveform)

    def set_snapshot(self, snapshot):
        if not isinstance(snapshot, dict):
            return
        if snapshot.get("microphone_active"):
            state = "Listening"
        elif snapshot.get("microphone_available"):
            state = "Ready"
        else:
            state = "Disconnected"
        self.state_label.setText(state)
        self.device_label.setText(snapshot.get("selected_microphone") or "Unavailable")
        self.waveform.set_level(snapshot.get("input_level", 0.0))


class TaskPanel(HudPanel):
    pauseRequested = Signal()
    resumeRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, parent=None):
        super().__init__("Current Task", parent)
        self.values = {key: _value_label("Waiting") for key in (
            "description", "application", "mode", "step", "status", "elapsed",
        )}
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(3)
        for label, key in (
            ("TASK", "description"), ("APP", "application"),
            ("MODE", "mode"), ("STEP", "step"),
            ("STATE", "status"), ("ELAPSED", "elapsed"),
        ):
            form.addRow(label, self.values[key])
        self.content.addLayout(form)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.content.addWidget(self.progress)
        controls = QHBoxLayout()
        self.pause_button = QPushButton("PAUSE")
        self.resume_button = QPushButton("RESUME")
        self.cancel_button = QPushButton("CANCEL")
        self.cancel_button.setObjectName("danger")
        self.pause_button.clicked.connect(self.pauseRequested)
        self.resume_button.clicked.connect(self.resumeRequested)
        self.cancel_button.clicked.connect(self.cancelRequested)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.resume_button)
        controls.addWidget(self.cancel_button)
        self.content.addLayout(controls)
        self._started_at = None
        self._status = "idle"
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._elapsed_timer.start(1000)
        self.set_snapshot({})

    def set_snapshot(self, snapshot):
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        status = str(snapshot.get("status") or "idle").lower()
        if status in {"running", "paused"} and self._started_at is None:
            self._started_at = time.monotonic()
        if status in {"completed", "cancelled", "failed", "idle"} and self._status not in {"running", "paused"}:
            self._started_at = None
        self._status = status
        self.values["description"].setText(snapshot.get("description") or "Waiting")
        self.values["application"].setText(snapshot.get("application") or "Waiting")
        self.values["mode"].setText(snapshot.get("mode") or "Waiting")
        self.values["step"].setText(snapshot.get("step") or "Waiting")
        self.values["status"].setText(normalize_state(status))
        self.progress.setValue(int(snapshot.get("progress") or 0))
        self.pause_button.setEnabled(status == "running")
        self.resume_button.setEnabled(status == "paused")
        self.cancel_button.setEnabled(status in {"running", "paused"})
        self._update_elapsed()

    def _update_elapsed(self):
        if self._started_at is None:
            self.values["elapsed"].setText("Unavailable")
            return
        elapsed = max(0, int(time.monotonic() - self._started_at))
        self.values["elapsed"].setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")


class ReasoningPanel(HudPanel):
    def __init__(self, parent=None):
        super().__init__("Execution Summary", parent, compact=True)
        self.values = {}
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(3)
        for label, key in (
            ("GOAL", "goal"), ("PLANNER", "planner"),
            ("CAPABILITY", "capability"), ("CURRENT", "step"),
            ("RETRIES", "retries"), ("RECOVERY", "recovery"),
        ):
            self.values[key] = _value_label("Waiting" if key != "retries" else "Unavailable")
            form.addRow(label, self.values[key])
        self.content.addLayout(form)

    def set_goal(self, text):
        self.values["goal"].setText(str(text or "Waiting"))

    def begin_goal(self, text):
        """Reset per-command execution fields before showing a new goal."""
        self.set_goal(text)
        self.set_planner("Waiting")
        self.set_capability("Waiting")
        self.set_step("Waiting")
        self.values["retries"].setText("Unavailable")
        self.set_recovery("Waiting")

    def set_capability(self, text):
        self.values["capability"].setText(str(text or "Waiting"))

    def set_step(self, text):
        self.values["step"].setText(str(text or "Waiting"))

    def set_planner(self, text):
        self.values["planner"].setText(str(text or "Unavailable"))

    def set_recovery(self, text):
        self.values["recovery"].setText(str(text or "Waiting"))


class HermesPanel(HudPanel):
    approveRequested = Signal(str)
    denyRequested = Signal(str)
    cancelRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__("Hermes Orchestrator", parent, compact=True)
        self.status = _value_label("Disabled")
        self.task = _value_label("Unavailable")
        self.task_status = _value_label("Idle")
        self.steps = _value_label("Unavailable")
        self.progress = _value_label("0%")
        self.capabilities = _value_label("Unavailable")
        self.plan_summary = _value_label("Unavailable")
        self.requested_capabilities = _value_label("Unavailable")
        self.elapsed = _value_label("0.0 s")
        self.retries = _value_label("0")
        self.confirmations = _value_label("0")
        self.output = _value_label("Unavailable")
        self._task_id = ""
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("STATE", self.status)
        form.addRow("TASK", self.task)
        form.addRow("TASK STATE", self.task_status)
        form.addRow("STEPS", self.steps)
        form.addRow("PROGRESS", self.progress)
        form.addRow("CAPABILITIES", self.capabilities)
        form.addRow("PLAN", self.plan_summary)
        form.addRow("REQUESTED TOOLS", self.requested_capabilities)
        form.addRow("ELAPSED", self.elapsed)
        form.addRow("RETRIES", self.retries)
        form.addRow("CONFIRMATIONS", self.confirmations)
        form.addRow("OUTPUT", self.output)
        self.content.addLayout(form)
        controls = QHBoxLayout()
        self.approve_button = QPushButton("APPROVE ONCE")
        self.approve_button.setObjectName("hermesApprove")
        self.deny_button = QPushButton("DENY")
        self.deny_button.setObjectName("hermesDeny")
        self.cancel_button = QPushButton("CANCEL TASK")
        self.cancel_button.setObjectName("danger")
        self.approve_button.clicked.connect(
            lambda: self.approveRequested.emit(self._task_id)
        )
        self.deny_button.clicked.connect(
            lambda: self.denyRequested.emit(self._task_id)
        )
        self.cancel_button.clicked.connect(
            lambda: self.cancelRequested.emit(self._task_id)
        )
        for button in (self.approve_button, self.deny_button, self.cancel_button):
            controls.addWidget(button)
        self.content.addLayout(controls)
        self.approve_button.setEnabled(False)
        self.deny_button.setEnabled(False)
        self.cancel_button.setEnabled(False)

    def set_snapshot(self, snapshot):
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        self._task_id = str(snapshot.get("hermes_task_id") or "")
        self.status.setText(normalize_state(snapshot.get("hermes", "Disabled")))
        self.task.setText(snapshot.get("hermes_task") or "Unavailable")
        self.task_status.setText(normalize_state(snapshot.get("hermes_task_status", "Idle")))
        self.steps.setText(str(snapshot.get("hermes_steps", "Unavailable")))
        self.progress.setText(f"{int(snapshot.get('hermes_progress', 0) or 0)}%")
        self.capabilities.setText(str(snapshot.get("hermes_capabilities") or "Unavailable"))
        self.plan_summary.setText(str(snapshot.get("hermes_plan_summary") or "Unavailable"))
        self.requested_capabilities.setText(str(
            snapshot.get("hermes_requested_capabilities") or "Unavailable"
        ))
        self.elapsed.setText(f"{float(snapshot.get('hermes_elapsed', 0.0) or 0.0):.1f} s")
        self.retries.setText(str(snapshot.get("hermes_retries", 0)))
        self.confirmations.setText(str(snapshot.get("hermes_confirmations", 0)))
        self.output.setText(str(snapshot.get("hermes_output") or "Unavailable"))
        approval_pending = bool(snapshot.get("hermes_approval_pending"))
        task_state = str(snapshot.get("hermes_task_status") or "").upper()
        self.approve_button.setEnabled(bool(self._task_id) and approval_pending)
        self.deny_button.setEnabled(bool(self._task_id) and approval_pending)
        self.cancel_button.setEnabled(bool(self._task_id) and task_state in {
            "QUEUED", "PLANNING", "WAITING_CONFIRMATION", "RUNNING",
            "PAUSED", "RETRYING", "ROLLING_BACK",
        })


class CapabilitySummaryPanel(HudPanel):
    openRequested = Signal()

    def __init__(self, parent=None):
        super().__init__("Capabilities", parent, compact=True)
        self.summary = _value_label("Waiting for capability scan")
        self.content.addWidget(self.summary)
        self.list = QListWidget()
        self.list.setMaximumHeight(112)
        self.content.addWidget(self.list)
        self.open_button = QPushButton("VIEW REGISTRY")
        self.open_button.clicked.connect(self.openRequested)
        self.content.addWidget(self.open_button)

    def set_report(self, report):
        report = report if isinstance(report, dict) else {}
        total = report.get("total", 0)
        counts = report.get("counts", {})
        self.summary.setText(f"{total} registered · " + ", ".join(
            f"{key}: {value}" for key, value in sorted(counts.items())
        ))
        self.list.clear()
        for record in list(report.get("capabilities", []))[:6]:
            self.list.addItem(
                f"{record.get('capability_id', 'Unknown')}  ·  {record.get('status', 'Unavailable')}"
            )


class ApplicationsPanel(HudPanel):
    closeSelected = Signal(str)
    focusSelected = Signal(str)
    closeAll = Signal()

    def __init__(self, parent=None):
        super().__init__("Active Applications", parent, compact=True)
        self.items = QListWidget()
        self.items.setMinimumHeight(116)
        self.content.addWidget(self.items, 1)
        controls = QHBoxLayout()
        self.focus_button = QPushButton("FOCUS")
        self.close_button = QPushButton("CLOSE")
        self.close_all_button = QPushButton("CLOSE ALL")
        self.close_all_button.setObjectName("danger")
        self.focus_button.clicked.connect(lambda: self.focusSelected.emit(self.selected_name()))
        self.close_button.clicked.connect(lambda: self.closeSelected.emit(self.selected_name()))
        self.close_all_button.clicked.connect(self.closeAll)
        controls.addWidget(self.focus_button)
        controls.addWidget(self.close_button)
        controls.addWidget(self.close_all_button)
        self.content.addLayout(controls)
        self._raw = []

    def set_items(self, items):
        current_id = self.items.currentItem().data(Qt.UserRole) if self.items.currentItem() else None
        self._raw = list(items or [])
        self.items.clear()
        restore_row = -1
        for row, entry in enumerate(self._raw):
            name = entry.get("display_name") or entry.get("name") or "Unknown"
            kind = entry.get("type", "item")
            state = entry.get("state", "open")
            owned = "owned" if entry.get("opened_by_jarvis", True) else "external"
            item = QListWidgetItem(f"{name}\n{kind} · {state} · {owned}")
            item.setData(Qt.UserRole, entry.get("id"))
            self.items.addItem(item)
            if entry.get("id") == current_id:
                restore_row = row
        if restore_row >= 0:
            self.items.setCurrentRow(restore_row)

    def selected_name(self):
        row = self.items.currentRow()
        if 0 <= row < len(self._raw):
            return str(self._raw[row].get("display_name") or self._raw[row].get("name") or "")
        return ""


class OfficeBrowserPanel(HudPanel):
    def __init__(self, parent=None):
        super().__init__("Workspace State", parent, compact=True)
        self.values = {}
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        for label, key in (
            ("BROWSER", "browser"), ("WORD", "word"), ("EXCEL", "excel"),
            ("POWERPOINT", "powerpoint"), ("RESEARCH", "research"),
            ("PREVIEW", "preview"),
        ):
            self.values[key] = _value_label("Unavailable")
            form.addRow(label, self.values[key])
        self.content.addLayout(form)

    def set_snapshot(self, snapshot):
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        for key in ("browser", "word", "excel", "powerpoint", "research"):
            self.values[key].setText(normalize_state(snapshot.get(key, "Unavailable")))
        self.values["preview"].setText(snapshot.get("live_preview") or "Unavailable")


class SystemMetricsPanel(HudPanel):
    def __init__(self, parent=None):
        super().__init__("System Metrics", parent, compact=True)
        gauges = QHBoxLayout()
        self.gauges = {
            "cpu_percent": CircularGauge("CPU"),
            "ram_percent": CircularGauge("RAM"),
            "disk_percent": CircularGauge("DISK"),
        }
        for gauge in self.gauges.values():
            gauges.addWidget(gauge)
        self.content.addLayout(gauges)
        self.detail = _value_label("GPU: Unavailable · NET: Unavailable · Workers: Unavailable")
        self.content.addWidget(self.detail)

    def set_metrics(self, metrics):
        metrics = metrics if isinstance(metrics, dict) else {}
        for key, gauge in self.gauges.items():
            gauge.set_value(metrics.get(key))
        gpu = metrics.get("gpu_percent")
        sent = metrics.get("network_sent_bytes")
        received = metrics.get("network_received_bytes")
        threads = metrics.get("python_threads")
        gpu_text = "Unavailable" if gpu is None else f"{float(gpu):.1f}%"
        network_text = "Unavailable" if sent is None or received is None else (
            f"↑ {float(sent) / (1024 ** 2):.1f} MiB  ↓ {float(received) / (1024 ** 2):.1f} MiB"
        )
        threads_text = "Unavailable" if threads is None else str(threads)
        self.detail.setText(f"GPU: {gpu_text} · NET: {network_text} · THREADS: {threads_text}")


class TaskTimelinePanel(HudPanel):
    def __init__(self, parent=None):
        super().__init__("Task Timeline", parent, compact=True)
        self.events = QListWidget()
        self.events.setMinimumHeight(120)
        self.content.addWidget(self.events, 1)

    def add_event(self, stage, detail, timestamp=None):
        stamp = timestamp or time.strftime("%H:%M:%S")
        self.events.addItem(f"{stamp}  {str(stage).upper()}\n{detail}")
        self.events.scrollToBottom()
        while self.events.count() > 300:
            self.events.takeItem(0)


class QuickActionsPanel(HudPanel):
    actionRequested = Signal(str)

    ACTIONS = (
        ("START VOICE", "start_voice"),
        ("STOP VOICE", "stop_voice"),
        ("MUTE SPEECH", "mute_speech"),
        ("OPEN BROWSER", "open_browser"),
        ("OPEN APP", "open_application"),
        ("OPEN FOLDER", "open_folder"),
        ("SCREENSHOT", "screenshot"),
        ("SELF TEST", "selftest"),
        ("CAPABILITIES", "capabilities"),
        ("OPEN LOGS", "logs"),
        ("SETTINGS", "settings"),
        ("STOP TASK", "stop_task"),
        ("EMERGENCY STOP", "emergency_stop"),
    )

    def __init__(self, parent=None):
        super().__init__("Quick Actions", parent, compact=True)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self.buttons = {}
        for index, (label, action) in enumerate(self.ACTIONS):
            button = QPushButton(label)
            if action in {"stop_task", "emergency_stop"}:
                button.setObjectName("danger")
            button.clicked.connect(lambda _checked=False, key=action: self.actionRequested.emit(key))
            self.buttons[action] = button
            grid.addWidget(button, index // 2, index % 2)
        self.content.addLayout(grid)
