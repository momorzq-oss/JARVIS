"""
JARVIS desktop (GUI) entry point.

Launches the PySide6 window first, then loads the assistant backend in the
background with staged status updates. Console output appears only when
launched with --debug. Normal mode opens a graphical window with no console.

    python desktop_main.py            # GUI, no console output
    python desktop_main.py --debug    # GUI + console diagnostics
"""
import argparse
import concurrent.futures
import os
import sys
import time


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
    p.add_argument("--no-auto-voice", action="store_true",
                   help="diagnostic launch: do not auto-start saved voice mode")
    p.add_argument("--exit-after-seconds", type=float, default=0.0,
                   help=argparse.SUPPRESS)
    return p.parse_args(argv)


def _startup_preload_enabled(args):
    """Keep the diagnostic preload switch authoritative for every path."""
    return not bool(args.skip_model_preload)


def _auto_voice_requested(args, settings):
    return bool(
        args.start_voice
        or (settings.get("start_voice_automatically", False)
            and not args.no_auto_voice)
    )


def _run_background_startup(
    controller, bridge, registry_items,
    *, auto_voice_requested=False, preload_enabled=True,
    run_capability_scan=True,
):
    """Initialize latency-sensitive voice before optional health discovery.

    Capability discovery imports and probes many optional integrations.  In a
    frozen cold start it can take over a minute, but microphone readiness must
    not depend on that non-critical inventory.  The order remains serialized:
    audio initialization finishes before model preload and capability scans,
    so native audio/model startup does not race those probes.
    """
    for message in (
        "Loading configuration", "Loading microphone", "Loading Whisper",
        "Loading wake word", "Loading Piper", "Loading browser support",
        "Loading assistant backend",
    ):
        bridge.statusChanged.emit(message)
    # Input readiness is independent of Piper's output-device probe.  On a
    # cold Windows/PortAudio start that probe can take several seconds, so
    # open the microphone and wake model first while still keeping all audio
    # initialization serialized in this one worker.
    voice_started = None
    if auto_voice_requested:
        voice_started = bool(controller.start_voice())
    controller.apply_settings()
    if auto_voice_requested:
        bridge.autoVoiceStarted.emit(bool(voice_started))
    if preload_enabled:
        controller.preload_models()
    if not run_capability_scan:
        bridge.statusChanged.emit("Ready")
        bridge.registry.emit(registry_items())
        bridge.startupCompleted.emit()
        return
    _finish_background_startup(controller, bridge, registry_items)


def _finish_background_startup(controller, bridge, registry_items):
    """Run non-critical inventory after latency-sensitive startup settles."""
    controller.start_capability_scan()
    bridge.statusChanged.emit("Ready")
    bridge.registry.emit(registry_items())
    bridge.startupCompleted.emit()


def _queue_deferred_capability_scan(schedule, run_async, scan, delay_ms=20_000):
    """Queue inventory after auto-voice and its first Piper greeting settle."""
    schedule(int(delay_ms), lambda: run_async(scan))


def main(argv=None):
    args = _parse_args(argv)
    startup_started = time.perf_counter()

    if not _acquire_single_instance():
        return 0

    from PySide6.QtCore import QCoreApplication, Qt, QTimer
    from PySide6.QtGui import QColor, QFont, QPalette
    from PySide6.QtWidgets import (
        QApplication, QLabel, QProgressBar, QSystemTrayIcon, QVBoxLayout,
        QWidget,
    )

    from config import Config, ensure_dirs
    from core.settings import SettingsStore
    from gui import styles
    from gui.workers import GuiController
    from gui.main_window import MainWindow
    from gui.settings_window import SettingsWindow
    from gui.tray import TrayIcon

    ensure_dirs()
    _attach_hidden_stdio(Config.LOG_DIR)

    # A no-console launch must leave actionable evidence if native imports or
    # widget construction stalls before the window is shown.  Cancel the
    # watchdog immediately after first paint so normal runtime stays quiet.
    import faulthandler
    startup_trace = open(
        Config.LOG_DIR / "startup_stack.log", "a", encoding="utf-8", buffering=1
    )
    faulthandler.enable(file=startup_trace)
    faulthandler.dump_traceback_later(30, repeat=True, file=startup_trace)

    from voice import audio_log

    def startup_phase(name):
        audio_log.log(
            f"Desktop startup phase: {name} "
            f"({time.perf_counter() - startup_started:.3f}s)"
        )

    app = QApplication(sys.argv[:1])
    startup_phase("QApplication created")
    app.setApplicationName("JARVIS")
    app.setQuitOnLastWindowClosed(False)   # live in tray after window closes

    settings = SettingsStore()
    auto_voice_requested = _auto_voice_requested(args, settings)
    app.setStyle("Fusion")
    application_palette = app.palette()
    application_palette.setColor(QPalette.Window, QColor(styles.BG_DEEP))
    application_palette.setColor(QPalette.WindowText, QColor(styles.TEXT))
    application_palette.setColor(QPalette.Base, QColor("#07101D"))
    application_palette.setColor(QPalette.AlternateBase, QColor(styles.BG_PANEL_SOLID))
    application_palette.setColor(QPalette.Text, QColor(styles.TEXT))
    application_palette.setColor(QPalette.Button, QColor(styles.BG_PANEL_SOLID))
    application_palette.setColor(QPalette.ButtonText, QColor(styles.TEXT))
    application_palette.setColor(QPalette.Highlight, QColor(styles.CYAN))
    application_palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    application_palette.setColor(QPalette.ToolTipBase, QColor(styles.BG_PANEL_SOLID))
    application_palette.setColor(QPalette.ToolTipText, QColor(styles.TEXT))
    app.setPalette(application_palette)
    app.setFont(QFont("Segoe UI", 9))
    startup_phase("theme prepared")

    # Paint a real, dark, responsive surface before loading native audio,
    # automation, provider, or the large mission-control widget tree.
    startup_window = QWidget()
    startup_window.setWindowTitle("JARVIS · Starting")
    startup_window.setMinimumSize(620, 260)
    startup_palette = startup_window.palette()
    startup_palette.setColor(QPalette.Window, QColor("#050A12"))
    startup_palette.setColor(QPalette.WindowText, QColor("#D9EAF4"))
    startup_palette.setColor(QPalette.Highlight, QColor("#00D1FF"))
    startup_window.setPalette(startup_palette)
    startup_window.setAutoFillBackground(True)
    startup_layout = QVBoxLayout(startup_window)
    startup_layout.setContentsMargins(54, 48, 54, 48)
    startup_title = QLabel("J A R V I S")
    startup_title.setObjectName("startupTitle")
    startup_title.setFont(QFont("Consolas", 30, QFont.Bold))
    title_palette = startup_title.palette()
    title_palette.setColor(QPalette.WindowText, QColor("#8AECFF"))
    startup_title.setPalette(title_palette)
    startup_status_label = QLabel("Loading trusted desktop services")
    startup_status_label.setObjectName("startupStatus")
    startup_status_label.setFont(QFont("Segoe UI", 13))
    status_palette = startup_status_label.palette()
    status_palette.setColor(QPalette.WindowText, QColor("#83DFF0"))
    startup_status_label.setPalette(status_palette)
    startup_progress_bar = QProgressBar()
    startup_progress_bar.setRange(0, 0)
    startup_layout.addStretch(1)
    startup_layout.addWidget(startup_title)
    startup_layout.addWidget(startup_status_label)
    startup_layout.addWidget(startup_progress_bar)
    startup_layout.addStretch(1)
    startup_window.show()
    startup_window.raise_()
    startup_window.activateWindow()
    app.processEvents()
    startup_phase("startup shell shown")

    def update_startup(message):
        startup_status_label.setText(str(message))
        app.processEvents()

    # ---- startup status ------------------------------------------------
    def startup_status(msg):
        window.current_status.setText(f"Status: {msg}")
        window.status_chip.setText(msg.upper())

    # ---- controller + window ---------------------------------------------
    update_startup("Initializing Windows audio safely")
    try:
        from voice.devices import initialize_audio_backend
        initialize_audio_backend()
        audio_log.log("Windows audio backend initialized on main thread")
    except Exception as exc:
        # Voice startup will report the same actionable error while typed
        # commands and the GUI remain usable.
        audio_log.log_error(f"Windows audio backend unavailable: {exc}", exc)
    app.processEvents()
    update_startup("Loading command, voice, and automation services")

    def build_controller():
        from core.assistant_controller import AssistantController
        built_controller = AssistantController(
            skip_preload=args.skip_model_preload, debug=args.debug
        )
        return built_controller

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="JARVIS-Startup"
    ) as startup_pool:
        controller_future = startup_pool.submit(build_controller)
        while not controller_future.done():
            app.processEvents()
            time.sleep(0.02)
        controller = controller_future.result()

    gui_controller = GuiController(controller=controller,
                                   skip_preload=args.skip_model_preload,
                                   debug=args.debug)
    startup_phase("GUI controller created")
    startup_watchdog_active = {"value": True}

    def finish_startup_watchdog():
        if not startup_watchdog_active["value"]:
            return
        startup_watchdog_active["value"] = False
        faulthandler.cancel_dump_traceback_later()
        try:
            startup_trace.close()
        except Exception:
            pass

    # Keep diagnostic stacks enabled through the native voice/background
    # startup, not merely until the first frame has painted.
    gui_controller.bridge.startupCompleted.connect(finish_startup_watchdog)
    gui_controller.controller.voice_diagnostic = args.voice_diagnostic
    gui_controller.controller.attach_settings(settings, initialize_audio=False)
    startup_phase("settings attached")
    update_startup("Building cinematic mission control")
    window = MainWindow(
        gui_controller, settings, startup_progress=update_startup
    )
    startup_phase("main window constructed")
    # The application palette already guarantees a dark first frame without
    # invoking Qt's expensive native stylesheet selector engine.
    window.setAutoFillBackground(True)
    window.showMaximized()
    app.processEvents()
    startup_window.close()
    startup_phase("main window shown")
    startup_status("Starting JARVIS")

    def apply_cinematic_theme():
        app.setPalette(application_palette)
        startup_phase("cinematic theme applied")
        gui_controller.run_async(run_startup)
        startup_phase("background startup scheduled")

    QTimer.singleShot(50, apply_cinematic_theme)

    # ---- tray --------------------------------------------------------------
    tray = TrayIcon(app)
    tray.show()
    startup_phase("tray ready")

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
    if auto_voice_requested:
        gui_controller.bridge.autoVoiceStarted.connect(
            window._on_auto_voice_started
        )
        deferred_scan_queued = False

        def queue_deferred_capability_scan():
            nonlocal deferred_scan_queued
            if deferred_scan_queued:
                return
            deferred_scan_queued = True
            _queue_deferred_capability_scan(
                QTimer.singleShot,
                gui_controller.run_async,
                gui_controller.controller.start_capability_scan,
            )

        gui_controller.bridge.startupCompleted.connect(
            queue_deferred_capability_scan
        )

    def run_startup():
        _run_background_startup(
            gui_controller.controller,
            gui_controller.bridge,
            gui_controller.registry_items,
            auto_voice_requested=auto_voice_requested,
            preload_enabled=(
                _startup_preload_enabled(args) and not auto_voice_requested
            ),
            run_capability_scan=not auto_voice_requested,
        )

    # speak the greeting only once the GUI is visible
    def greet():
        try:
            from main import greeting
            gui_controller.speak(greeting())
        except Exception:
            pass

    if auto_voice_requested:
        window.autoVoiceReady.connect(lambda _started: greet())
    else:
        QTimer.singleShot(1200, greet)

    # ---- shutdown ----------------------------------------------------------
    exit_started = False

    def full_exit():
        nonlocal exit_started
        if exit_started:
            return
        exit_started = True
        finish_startup_watchdog()
        startup_status("Powering down")
        audio_log.log("Desktop full exit requested")
        try:
            window.prepare_shutdown()
        except Exception:
            pass
        try:
            gui_controller.shutdown()
        except Exception:
            pass
        tray.hide()
        app.setQuitOnLastWindowClosed(True)
        window.hide()
        audio_log.log("Desktop requesting Qt event-loop exit")
        app.quit()
        QCoreApplication.exit(0)

    window.exitRequested.connect(full_exit)
    tray.exitRequested.connect(full_exit)
    if args.exit_after_seconds > 0:
        QTimer.singleShot(
            max(1, int(args.exit_after_seconds * 1000)), full_exit,
        )

    # intercept window close -> minimize to tray
    original_close = window.closeEvent

    def close_event(event):
        if settings.get("minimize_to_tray", True) and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            minimize_to_tray()
        else:
            full_exit()

    window.closeEvent = close_event

    startup_phase("entering Qt event loop")
    exit_code = app.exec()
    audio_log.log(f"Desktop Qt event loop exited with code {exit_code}")
    activation_timer.stop()
    try:
        gui_controller.shutdown()
    except Exception:
        pass
    audio_log.log("Desktop final teardown complete")
    # PyInstaller applications load several native audio/ML runtimes.  Their
    # process-finalizer threads can occasionally remain suspended by Windows
    # even after Qt and every JARVIS service have shut down.  At this point all
    # application-owned resources are already closed, so bypass interpreter
    # finalizers in the frozen build to guarantee that Exit really exits.
    if getattr(sys, "frozen", False):
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(int(exit_code))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
