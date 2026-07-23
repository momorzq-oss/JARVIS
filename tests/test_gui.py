"""GUI tests (offscreen). Verify the window builds, panels update, and the
application list reflects the session registry without blocking the GUI."""
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from config import ensure_dirs
from core.settings import SettingsStore
from gui import styles
from gui.workers import GuiController
from gui.main_window import MainWindow
from gui.widgets.hud import StatusIndicator
from gui.settings_window import SettingsWindow

from tests.test_controller import make_ctx


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(styles.APP_QSS)
    yield app


@pytest.fixture()
def window(qapp, tmp_path):
    ensure_dirs()
    settings = SettingsStore(tmp_path / "config.json")
    gc = GuiController(controller=None, skip_preload=True, debug=True)
    # swap the heavy ctx for the lightweight fake
    gc.controller.ctx = make_ctx()
    gc.controller.status_snapshot = lambda: {
        "state": "ready", "system_metrics": {}, "sessions": 0,
    }
    w = MainWindow(gc, settings)
    yield w
    w.close()
    w.deleteLater()


def test_window_builds_with_all_buttons(window):
    for attr in ("btn_start", "btn_stop", "btn_mute", "btn_browser", "btn_files",
                 "btn_logs", "btn_settings", "btn_send", "btn_min", "btn_exit"):
        assert hasattr(window, attr), attr


def test_status_indicator_initializes_without_forced_repolish(qapp, monkeypatch):
    calls = []
    original = StatusIndicator.set_state

    def observed(self, value, repolish=True):
        calls.append((value, repolish))
        return original(self, value, repolish=repolish)

    monkeypatch.setattr(StatusIndicator, "set_state", observed)
    indicator = StatusIndicator("Voice")
    assert calls == [("WAITING", False)]
    assert indicator.property("hudState") == "warning"


def test_window_title_and_core(window):
    assert "JARVIS" in window.windowTitle()
    assert window.core is not None


def test_state_updates_core_and_status(window):
    window._slot_state("recording", "Recording command")
    assert "recording" in window.current_status.text().lower()
    assert window.core._state == "recording"


def test_registry_panel_updates(window):
    items = [
        {"id": "a", "type": "app", "name": "Notepad", "state": "open",
         "opened_at": time.time()},
        {"id": "b", "type": "browser_tab", "name": "YouTube", "state": "open",
         "opened_at": time.time()},
    ]
    window._fill_registry(items)
    assert window.apps.count() == 2
    assert "Notepad" in window.apps.item(0).text()
    assert "YouTube" in window.apps.item(1).text()


def test_registry_panel_reflects_close(window):
    items = [{"id": "a", "type": "app", "name": "Notepad", "state": "open",
              "opened_at": time.time()}]
    window._fill_registry(items)
    assert window.apps.count() == 1
    window._fill_registry([])  # after closing
    assert window.apps.count() == 0


def test_timeline_records_stages(window):
    window._slot_timeline("heard", "open notepad")
    window._slot_timeline("cleaned", "open notepad")
    assert window.timeline.count() == 2
    assert window.fields["cleaned"].text() == "open notepad"


def test_transcription_field_updates(window):
    window.gc.bridge.transcription.emit("hello jarvis")
    QApplication.processEvents()
    assert window.fields["transcription"].text() == "hello jarvis"


def test_send_button_submits_typed_command(window, monkeypatch):
    submitted = []
    monkeypatch.setattr(window.gc, "submit_text", lambda t: submitted.append(t))
    window.input.setText("open downloads")
    window._on_send()
    assert submitted == ["open downloads"]
    assert window.input.text() == ""


def test_command_shortcut_focuses_shared_input(window):
    window._show_page("settings")
    window.input.setText("replace me")
    window._focus_command_input()
    assert window.pages.currentWidget() is window.dashboard
    assert window.input.selectedText() == "replace me"


def test_status_refresh_never_blocks_gui_thread(window, monkeypatch):
    deadline = time.monotonic() + 1
    while window.gc._status_refresh_pending and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert window.gc._status_refresh_pending is False
    entered = threading.Event()
    release = threading.Event()

    def slow_status():
        entered.set()
        release.wait(timeout=2)
        return {"state": "ready", "system_metrics": {}}

    monkeypatch.setattr(window.gc.controller, "status_snapshot", slow_status)
    started = time.perf_counter()
    assert window.gc.refresh_status_async() is True
    elapsed = time.perf_counter() - started
    try:
        assert elapsed < 0.25
        assert entered.wait(timeout=1)
        assert window.gc.refresh_status_async() is False
    finally:
        release.set()


def test_voice_toggle_calls_controller(window, monkeypatch):
    calls = {"start": 0, "stop": 0}
    monkeypatch.setattr(window.gc, "start_voice",
                        lambda: calls.__setitem__("start", calls["start"] + 1) or True)
    monkeypatch.setattr(window.gc, "stop_voice",
                        lambda: calls.__setitem__("stop", calls["stop"] + 1) or True)
    window._on_start_voice()
    window._on_stop_voice()
    assert calls == {"start": 1, "stop": 1}


def test_status_bridge_restores_live_wake_state_after_piper_completion(window):
    window.gc._forward_status({
        "speaker_state": "speaking",
        "microphone_active": True,
        "wakeword_active": True,
    })
    QApplication.processEvents()
    assert window.core._state == "speaking"

    window.gc._forward_status({
        "speaker_state": "ready",
        "microphone_active": True,
        "wakeword_active": True,
    })
    QApplication.processEvents()
    assert window.core._state == "listening_wake"
    assert "Waiting for Hey Jarvis" in window.dashboard.state_banner.text()


def test_hermes_settings_use_real_cli_mode_and_official_setup(qapp, tmp_path, monkeypatch):
    launched = []

    class Controller:
        bridge = None

        def open_hermes_provider_setup(self):
            launched.append(True)
            return True

        def apply_settings(self):
            return True

    monkeypatch.setattr(SettingsWindow, "_populate_devices", lambda self: None)
    dialog = SettingsWindow(
        SettingsStore(tmp_path / "settings.json"), Controller(),
    )

    mode = dialog._widgets["hermes_mode"][1]
    assert {mode.itemText(index) for index in range(mode.count())} == {"cli", "disabled"}
    assert not dialog._widgets["hermes_background_enabled"][1].isEnabled()
    assert not dialog._widgets["hermes_schedules_enabled"][1].isEnabled()
    assert not dialog._widgets["hermes_learning_enabled"][1].isEnabled()
    approval = dialog._widgets["hermes_approval_mode"][1]
    assert [approval.itemText(index) for index in range(approval.count())] == ["strict"]
    assert not approval.isEnabled()
    assert dialog._widgets["hermes_concurrency_limit"][1].maximum() == 2

    dialog.btn_configure_hermes.click()
    assert launched == [True]
    dialog._on_hermes_configuration({"state": "OPENED", "detail": "Official setup opened."})
    assert "OPENED" in dialog.hermes_status.text()
    dialog.close()
    dialog.deleteLater()


def test_hermes_settings_probe_runs_off_gui_thread(qapp, tmp_path, monkeypatch):
    probe_thread = []
    release = threading.Event()

    def snapshot(_manager):
        probe_thread.append(threading.current_thread().name)
        release.wait(1)
        return {"state": "READY", "detail": "Hermes Agent v0.test"}

    monkeypatch.setattr(SettingsWindow, "_populate_devices", lambda self: None)
    monkeypatch.setattr(
        "brain.hermes_runtime_manager.HermesRuntimeManager.snapshot", snapshot,
    )
    dialog = SettingsWindow(SettingsStore(tmp_path / "settings.json"))
    QApplication.processEvents()

    assert dialog._hermes_probe_running is True
    assert "Checking" in dialog.hermes_status.text()
    assert probe_thread == ["JARVIS-Hermes-Settings-Probe"]

    release.set()
    deadline = time.monotonic() + 2
    while dialog._hermes_probe_running and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)

    assert dialog.hermes_status.text() == "READY: Hermes Agent v0.test"
    assert dialog.btn_test_hermes.isEnabled()
    dialog.close()
    dialog.deleteLater()
