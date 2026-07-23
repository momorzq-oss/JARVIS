"""Three-column cinematic dashboard composed from reusable state widgets."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gui.widgets import (
    AICoreWidget,
    ApplicationsPanel,
    CapabilitySummaryPanel,
    ConversationPanel,
    DigitalClock,
    OfficeBrowserPanel,
    QuickActionsPanel,
    ReasoningPanel,
    SystemMetricsPanel,
    TaskPanel,
    TaskTimelinePanel,
    VoicePanel,
)
from gui.widgets.dashboard_panels import HermesPanel, WaveformWidget
from gui.widgets.hud import HudPanel


def _scroll_column(widget, minimum_width):
    scroll = QScrollArea()
    scroll.setObjectName("dashboardScroll")
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setMinimumWidth(minimum_width)
    scroll.setWidget(widget)
    return scroll


class DashboardPage(QWidget):
    commandSubmitted = Signal(str)
    quickActionRequested = Signal(str)
    pauseRequested = Signal()
    resumeRequested = Signal()
    cancelRequested = Signal()
    capabilityPageRequested = Signal()
    closeApplicationRequested = Signal(str)
    focusApplicationRequested = Signal(str)
    closeAllRequested = Signal()
    hermesApproveRequested = Signal()
    hermesDenyRequested = Signal()
    hermesCancelRequested = Signal()

    def __init__(self, reduced_motion=False, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("dashboardSplitter")
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(7)
        self.clock = DigitalClock()
        self.conversation = ConversationPanel()
        self.voice = VoicePanel()
        self.task = TaskPanel()
        left_layout.addWidget(self.clock)
        left_layout.addWidget(self.conversation, 2)
        left_layout.addWidget(self.voice)
        left_layout.addWidget(self.task, 1)
        left_layout.addStretch(1)
        splitter.addWidget(_scroll_column(left, 280))

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(4, 0, 4, 0)
        center_layout.setSpacing(7)
        self.core = AICoreWidget()
        self.core.set_reduce_motion(reduced_motion)
        center_layout.addWidget(self.core, 5)
        self.state_banner = QLabel("WAITING FOR BACKEND STATE")
        self.state_banner.setObjectName("stateBanner")
        self.state_banner.setAlignment(Qt.AlignCenter)
        center_layout.addWidget(self.state_banner)
        summaries = QHBoxLayout()
        summaries.setSpacing(7)
        self.reasoning = ReasoningPanel()
        self.hermes = HermesPanel()
        summaries.addWidget(self.reasoning, 3)
        summaries.addWidget(self.hermes, 2)
        center_layout.addLayout(summaries, 2)
        command_center = HudPanel("Command Signal", compact=True)
        self.command_waveform = WaveformWidget()
        self.command_waveform.set_reduce_motion(reduced_motion)
        command_center.content.addWidget(self.command_waveform)
        self.command_signal_status = QLabel("Waiting for audio or task activity")
        self.command_signal_status.setObjectName("dataValue")
        self.command_signal_status.setAlignment(Qt.AlignCenter)
        command_center.content.addWidget(self.command_signal_status)
        center_layout.addWidget(command_center)
        splitter.addWidget(_scroll_column(center, 380))

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(7)
        upper = QVBoxLayout()
        upper.setSpacing(7)
        self.capabilities = CapabilitySummaryPanel()
        self.applications = ApplicationsPanel()
        upper.addWidget(self.capabilities)
        upper.addWidget(self.applications)
        right_layout.addLayout(upper)
        self.workspace = OfficeBrowserPanel()
        right_layout.addWidget(self.workspace)
        self.metrics = SystemMetricsPanel()
        right_layout.addWidget(self.metrics)
        self.timeline = TaskTimelinePanel()
        right_layout.addWidget(self.timeline, 1)
        self.quick_actions = QuickActionsPanel()
        right_layout.addWidget(self.quick_actions)
        right_layout.addStretch(1)
        splitter.addWidget(_scroll_column(right, 360))

        splitter.setStretchFactor(0, 24)
        splitter.setStretchFactor(1, 43)
        splitter.setStretchFactor(2, 33)
        splitter.setSizes([310, 620, 520])
        root.addWidget(splitter, 1)

        self.conversation.commandSubmitted.connect(self.commandSubmitted)
        self.quick_actions.actionRequested.connect(self.quickActionRequested)
        self.task.pauseRequested.connect(self.pauseRequested)
        self.task.resumeRequested.connect(self.resumeRequested)
        self.task.cancelRequested.connect(self.cancelRequested)
        self.capabilities.openRequested.connect(self.capabilityPageRequested)
        self.applications.closeSelected.connect(self.closeApplicationRequested)
        self.applications.focusSelected.connect(self.focusApplicationRequested)
        self.applications.closeAll.connect(self.closeAllRequested)
        self.hermes.approveRequested.connect(self.hermesApproveRequested)
        self.hermes.denyRequested.connect(self.hermesDenyRequested)
        self.hermes.cancelRequested.connect(self.hermesCancelRequested)

    def set_reduce_motion(self, enabled):
        self.core.set_reduce_motion(enabled)
        self.voice.waveform.set_reduce_motion(enabled)
        self.command_waveform.set_reduce_motion(enabled)

    def set_state(self, state, detail=""):
        self.core.set_state(state, detail)
        pretty = str(state or "waiting").replace("_", " ").upper()
        self.state_banner.setText(pretty + (f"  ·  {detail}" if detail else ""))
        self.command_signal_status.setText(detail or pretty)

    def set_voice_snapshot(self, snapshot):
        self.voice.set_snapshot(snapshot)
        level = snapshot.get("input_level", 0.0) if isinstance(snapshot, dict) else 0.0
        self.core.set_level(level)
        self.command_waveform.set_level(level)
