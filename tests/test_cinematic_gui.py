"""Focused checks for the state-driven cinematic presentation layer."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from core.settings import SettingsStore
from gui import styles
from gui.main_window import MainWindow, NAVIGATION
from gui.widgets.ai_core_widget import AICoreWidget
from gui.workers import ControllerBridge, GuiController


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(styles.APP_QSS)
    yield app


@pytest.fixture()
def window(qapp, tmp_path):
    controller = GuiController(skip_preload=True, debug=True)
    settings = SettingsStore(tmp_path / "cinematic.json")
    result = MainWindow(controller, settings)
    yield result
    result.close()
    controller.shutdown()
    result.deleteLater()
    qapp.processEvents()


def test_all_requested_navigation_pages_are_real_widgets(window):
    assert set(window.page_map) == {key for _label, key in NAVIGATION}
    assert window.pages.count() == len(NAVIGATION)
    for key, widget in window.page_map.items():
        window._show_page(key)
        assert window.pages.currentWidget() is widget


def test_university_assignment_page_and_creator_credit_use_real_state(window):
    snapshot = {
        "university_assignment": {
            "assignment_type": "Essay",
            "topic": "Renewable Energy",
            "word_count": 1200,
            "citation_style": "APA 7",
            "academic_level": "Undergraduate",
            "current_section": "Discussion",
            "progress": 68,
            "source_count": 4,
            "reference_count": 4,
            "milestone_stage": "",
            "save_status": "Awaiting save location",
        }
    }
    window._slot_status(snapshot)
    assert "university" in window.page_map
    assert window.university_page.values["topic"].text() == "Renewable Energy"
    assert window.university_page.progress.value() == 68
    assert window.creator_credit.text() == "MADE BY BURABEEH"


def test_dashboard_widgets_consume_explicit_backend_state(window):
    snapshot = {
        "state": "executing",
        "microphone_available": True,
        "microphone_active": True,
        "wakeword_loaded": True,
        "wakeword_active": True,
        "whisper_loaded": True,
        "kimi": "ready",
        "hermes": "disabled",
        "desktop_agent": "ready",
        "browser": "open",
        "word": "closed",
        "excel": "closed",
        "powerpoint": "closed",
        "memory": "ready",
        "research": "active",
        "news": "ready",
        "system_metrics": {
            "cpu_percent": 12.5,
            "ram_percent": 40.0,
            "disk_percent": 55.0,
            "gpu_percent": None,
        },
    }
    window._slot_status(snapshot)
    assert window.subsystems.indicators["voice"].value_label.text() == "LISTENING"
    assert window.subsystems.indicators["hermes"].value_label.text() == "DISABLED"
    assert window.dashboard.metrics.gauges["cpu_percent"].value == 12.5
    assert "GPU: Unavailable" in window.dashboard.metrics.detail.text()


def test_core_motion_and_color_follow_real_state(window):
    window._slot_state("waiting_confirmation", "Approval required")
    assert window.core._state == "waiting_confirmation"
    assert "APPROVAL REQUIRED" in window.dashboard.state_banner.text().upper()
    window.dashboard.set_reduce_motion(True)
    assert window.core._reduce_motion is True
    assert window.dashboard.command_waveform._reduce_motion is True


def test_ai_core_uses_passive_cadence_while_waiting_for_wake_word(qapp):
    widget = AICoreWidget()
    widget.set_state("listening_wake", "Waiting for Hey Jarvis")
    assert widget._timer.interval() == widget.PASSIVE_INTERVAL_MS
    assert widget._timer.interval() >= 500
    widget.set_state("recording", "Listening to command")
    assert widget._timer.interval() == widget.ACTIVE_INTERVAL_MS
    widget.set_state("executing", "Running approved action")
    assert widget._timer.interval() == widget.ACTIVE_INTERVAL_MS
    widget.close()
    widget.deleteLater()


def test_ai_core_renders_armored_sentinel_geometry(qapp):
    widget = AICoreWidget()
    widget.resize(760, 760)
    widget.set_state("executing", "Executing verified capability graph")
    widget.set_level(0.7)
    widget.show()
    qapp.processEvents()
    image = widget.grab().toImage()

    def bright_pixels(left, top, right, bottom):
        count = 0
        for x in range(left, right, 4):
            for y in range(top, bottom, 4):
                pixel = image.pixelColor(x, y)
                if pixel.green() > 110 and pixel.blue() > 120:
                    count += 1
        return count

    assert bright_pixels(220, 70, 540, 220) > 25
    assert bright_pixels(35, 190, 725, 410) > 90
    assert bright_pixels(220, 315, 540, 570) > 180
    widget.close()
    widget.deleteLater()


def test_task_snapshot_drives_progress_and_controls(window):
    window._slot_taskstatus({
        "task_id": "real-task",
        "description": "Create a report",
        "application": "Microsoft Word",
        "mode": "LIVE_INTERACTIVE",
        "step": "Writing introduction",
        "progress": 61,
        "status": "running",
        "metadata": {"sources_found": 4},
    })
    assert window.task_progress.value() == 61
    assert window.btn_pause_task.isEnabled()
    assert not window.btn_resume_task.isEnabled()
    assert window.fields["app"].text() == "Microsoft Word"


def test_quick_actions_are_connected_to_real_handlers(window, monkeypatch):
    submitted = []
    monkeypatch.setattr(window.gc, "submit_text", submitted.append)
    window._handle_quick_action("open_browser")
    window._handle_quick_action("selftest")
    assert submitted == ["open the browser", "/selftest"]


def test_complete_semantic_signal_map_exists():
    bridge = ControllerBridge()
    names = (
        "state_changed", "voice_state_changed", "microphone_level_changed",
        "wake_word_state_changed", "transcript_changed", "cleaned_command_changed",
        "planner_state_changed", "hermes_state_changed", "task_started",
        "task_progress", "task_step_started", "task_step_completed",
        "task_step_failed", "task_waiting_confirmation", "task_completed",
        "task_cancelled", "task_failed", "speech_started",
        "speech_level_changed", "speech_finished", "capability_status_changed",
        "application_opened", "application_focused", "application_closed",
        "browser_state_changed", "office_state_changed", "research_state_changed",
        "system_metrics_changed", "audit_event", "emergency_stop_triggered",
        "startupCompleted",
    )
    assert all(hasattr(bridge, name) for name in names)


@pytest.mark.parametrize(
    "command",
    ("pause the current task", "resume typing", "cancel current task", "write faster"),
)
def test_live_task_controls_bypass_serial_command_queue(command):
    assert GuiController._is_task_control(command)


@pytest.mark.parametrize(
    "command",
    ("Pause.", "Resume", "Cancel", "Emergency stop", "Stop everything", "Stop speaking"),
)
def test_all_shared_router_control_aliases_bypass_long_tasks(command):
    assert GuiController._is_task_control(command)


def test_ordinary_commands_remain_serialized():
    assert not GuiController._is_task_control("open youtube")


def test_prepare_shutdown_stops_every_window_timer(window):
    from PySide6.QtCore import QTimer

    timers = window.findChildren(QTimer)
    assert timers
    for timer in timers:
        timer.start(100)

    window.prepare_shutdown()

    assert all(not timer.isActive() for timer in timers)


def test_gui_shutdown_rejects_new_commands_and_health_work(window):
    controller = window.gc

    controller.shutdown()

    assert controller.submit_text("open youtube") is False
    assert controller.run_async(lambda: None) is False
    assert controller.refresh_status_async() is False
