from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_desktop_launcher_uses_verified_python_312_runtime():
    launcher = (PROJECT_ROOT / "Launch JARVIS.vbs").read_text(encoding="utf-8")
    assert "Programs\\Python\\Python312\\python.exe" in launcher
    assert "pythoncore-3.14" not in launcher


def test_desktop_launcher_stays_silent_and_nonblocking():
    launcher = (PROJECT_ROOT / "Launch JARVIS.vbs").read_text(encoding="utf-8")
    assert "shell.Run command, 0, False" in launcher


def test_build_watchdog_survives_transient_wmi_failure():
    watchdog = (PROJECT_ROOT / "build" / "build_exe_watchdog.ps1").read_text(
        encoding="utf-8"
    )

    assert "Get-CimInstance Win32_Process -ErrorAction Stop" in watchdog
    assert "catch {" in watchdog
    assert "return @($ids)" in watchdog


def test_shortcut_installer_creates_desktop_and_start_menu_entries():
    installer = (PROJECT_ROOT / "install_shortcuts.ps1").read_text(
        encoding="utf-8"
    )

    assert "GetFolderPath('Desktop')" in installer
    assert "GetFolderPath('Programs')" in installer
    assert "System32\\wscript.exe" in installer
    assert "Launch JARVIS.vbs" in installer
    assert "Install-JarvisShortcut" in installer
