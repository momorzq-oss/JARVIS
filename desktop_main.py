"""
JARVIS desktop (GUI) entry point.

Launches the PySide6 window first, then loads the assistant backend in the
background with staged status updates. Console output appears only when
launched with --debug. Normal mode opens a graphical window with no console.

    python desktop_main.py            # GUI, no console output
    python desktop_main.py --debug    # GUI + console diagnostics
"""
import argparse
import os
import sys


_INSTANCE_MUTEX = None
_ACTIVATION_EVENT = None

_INSTANCE_MUTEX_NAME = "Local\\JARVISDesktopAssistant"
_ACTIVATION_EVENT_NAME = "Local\\JARVISDesktopAssistantActivate"


def _activate_existing_window():
    """Ask the live Qt process to restore its own window.

    Showing a tray-hidden QWidget through ``ShowWindow`` alone leaves Qt's
    internal visibility state out of sync with Windows.  On some systems that
    produces a title bar with a blank white client area.  A named event lets
    the existing GUI call ``showNormal`` on its own GUI thread instead.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenEventW.argtypes = (
            ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p,
        )
        kernel32.OpenEventW.restype = ctypes.c_void_p
        kernel32.SetEvent.argtypes = (ctypes.c_void_p,)
        kernel32.SetEvent.restype = ctypes.c_bool
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool
        event = kernel32.OpenEventW(0x0002, False, _ACTIVATION_EVENT_NAME)
        if event:
            kernel32.SetEvent(event)
            kernel32.CloseHandle(event)
    except Exception:
        pass


def _acquire_single_instance():
    """Allow only one GUI process, including when its window is in the tray."""
    global _INSTANCE_MUTEX, _ACTIVATION_EVENT
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (
            ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p,
        )
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, _INSTANCE_MUTEX_NAME)
        if not handle:
            return True  # Do not make a Windows API diagnostic prevent startup.
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            _activate_existing_window()
            return False
        _INSTANCE_MUTEX = handle  # retain the mutex for the process lifetime
        kernel32.CreateEventW.argtypes = (
            ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p,
        )
        kernel32.CreateEventW.restype = ctypes.c_void_p
        _ACTIVATION_EVENT = kernel32.CreateEventW(
            None, False, False, _ACTIVATION_EVENT_NAME,
        )
    except Exception:
        return True
    return True


def _consume_activation_request():
    """Return whether another launcher requested a Qt-owned window restore."""
    if os.name != "nt" or not _ACTIVATION_EVENT:
        return False
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        return kernel32.WaitForSingleObject(_ACTIVATION_EVENT, 0) == 0
    except Exception:
        return False


def _attach_hidden_stdio(log_dir):
    """Give no-console launches a durable log sink instead of ``None`` streams.

    WScript intentionally starts JARVIS with no terminal. Several optional
    native libraries still write diagnostics to stdout/stderr; a real file
    stream prevents those writes from terminating a worker or the process.
    """
    log_path = log_dir / "desktop_runtime.log"
    if sys.stdout is None:
        sys.stdout = open(log_path, "a", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = open(log_path, "a", encoding="utf-8", buffering=1)


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="JARVIS desktop GUI")
    p.add_argument("--debug", action="store_true", help="console diagnostics")
    p.add_argument("--skip-model-preload", action="store_true",
                   help="skip background model preload for faster startup")
    p.add_argument("--voice-diagnostic", action="store_true",
                   help="log live wake-word score/level/fps diagnostics")
    p.add_argument("--start-voice", action="store_true",
                   help="begin listening immediately after startup")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    if not _acquire_single_instance():
        return 0

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from config import Config, ensure_dirs
    from core.settings import SettingsStore
    from gui import styles
    from gui.workers import GuiController
    from gui.main_window import MainWindow
    from gui.settings_window import SettingsWindow
    from gui.tray import TrayIcon

    ensure_dirs()
    _attach_hidden_stdio(Config.LOG_DIR)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("JARVIS")
    app.setQuitOnLastWindowClosed(False)   # live in tray after window closes

    settings = SettingsStore()
    app.setStyleSheet(styles.theme_stylesheet(
        bool(settings.get("reduce_motion", False))
    ))

    # ---- startup status ------------------------------------------------
    def startup_status(msg):
        window.current_status.setText(f"Status: {msg}")
        window.status_chip.setText(msg.upper())

    # ---- controller + window ---------------------------------------------
    gui_controller = GuiController(skip_preload=args.skip_model_preload,
                                   debug=args.debug)
    gui_controller.controller.voice_diagnostic = args.voice_diagnostic
    gui_controller.controller.attach_settings(settings)
    window = MainWindow(gui_controller, settings)
    window.showMaximized()
    startup_status("Starting JARVIS")

    # ---- tray --------------------------------------------------------------
    tray = TrayIcon(app)
    tray.show()

    # ---- settings window ------------------------------------------------------
    # Keep a persistent reference so the dialog is never garbage-collected.
    app_state = {"settings_window": None}

    def open_settings():
        from voice import audio_log
        audio_log.log("Settings button clicked")
        try:
            dlg = app_state.get("settings_window")
            if dlg is None:
                dlg = SettingsWindow(
                    settings, gui_controller=gui_controller, parent=window
                )
                app_state["settings_window"] = dlg
                audio_log.log("Settings window created")
            dlg._load()               # refresh from current config each open
            dlg._populate_devices()
            audio_log.log("Settings loaded")
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            audio_log.log("Settings window shown")
        except Exception as exc:
            audio_log.log_error(f"Settings error: {exc}", exc)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(window, "Settings", f"Could not open settings: {exc}")

    window.settingsRequested.connect(open_settings)
    tray.settingsRequested.connect(open_settings)

    # ---- minimize / close-to-tray -------------------------------------------
    def minimize_to_tray():
        window.hide()
        tray.notify("JARVIS", "Still running in the system tray, sir.")

    window.minimizeRequested.connect(minimize_to_tray)

    def show_window():
        window.showNormal()
        window.raise_()
        window.activateWindow()

    tray.openRequested.connect(show_window)

    # A Desktop shortcut launch while JARVIS is minimized to the tray reaches
    # this timer.  Restore through Qt, never via a raw Win32 ShowWindow call.
    activation_timer = QTimer(app)
    activation_timer.setInterval(200)
    activation_timer.timeout.connect(
        lambda: show_window() if _consume_activation_request() else None
    )
    activation_timer.start()

    # ---- voice / mute / logs from tray ---------------------------------------
    tray.startVoiceRequested.connect(window._on_start_voice)
    tray.stopVoiceRequested.connect(window._on_stop_voice)
    tray.logsRequested.connect(window._on_logs)

    def tray_mute():
        window.btn_mute.setChecked(not window.btn_mute.isChecked())
        window._on_mute(window.btn_mute.isChecked())

    tray.muteRequested.connect(tray_mute)

    # ---- staged background startup ---------------------------------------------
    stages = [
        "Loading configuration", "Loading microphone", "Loading Whisper",
        "Loading wake word", "Loading Piper", "Loading browser support",
        "Loading assistant backend",
    ]

    def run_startup():
        for msg in stages:
            # marshal to GUI thread via the bridge status signal
            gui_controller.bridge.statusChanged.emit(msg)
        gui_controller.controller.preload_models()
        gui_controller.controller.start_capability_scan()
        gui_controller.bridge.statusChanged.emit("Ready")
        gui_controller.bridge.registry.emit(gui_controller.registry_items())

    gui_controller.run_async(run_startup)

    # speak the greeting only once the GUI is visible
    def greet():
        try:
            from main import greeting
            gui_controller.speak(greeting())
        except Exception:
            pass

    QTimer.singleShot(1200, greet)

    if args.start_voice or settings.get("start_voice_automatically", False):
        QTimer.singleShot(2000, window._on_start_voice)

    # ---- shutdown ----------------------------------------------------------
    def full_exit():
        startup_status("Powering down")
        try:
            gui_controller.shutdown()
        except Exception:
            pass
        tray.hide()
        app.quit()

    window.exitRequested.connect(full_exit)
    tray.exitRequested.connect(full_exit)

    # intercept window close -> minimize to tray
    original_close = window.closeEvent

    def close_event(event):
        if settings.get("minimize_to_tray", True) and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            minimize_to_tray()
        else:
            full_exit()

    window.closeEvent = close_event

    exit_code = app.exec()
    activation_timer.stop()
    try:
        gui_controller.shutdown()
    except Exception:
        pass
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
