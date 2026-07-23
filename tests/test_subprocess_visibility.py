"""Windows GUI helpers must not flash a terminal for background work."""
import sys
from types import SimpleNamespace

from skills import coder
from skills import system_control


class Process:
    pid = 42

    def poll(self):
        return None


def _expected_hidden_flags(module):
    return getattr(module.subprocess, "CREATE_NO_WINDOW", 0)


def test_normal_application_launch_is_direct_and_hidden(monkeypatch):
    observed = {}

    def fake_popen(args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)

    result = system_control._launch_app("word", SimpleNamespace())

    assert result == {"pid": 42, "how": "direct"}
    assert observed["args"] == ["winword"]
    assert observed["kwargs"]["shell"] is False
    assert observed["kwargs"].get("creationflags", 0) == _expected_hidden_flags(system_control)


def test_explicit_terminal_request_remains_visible(monkeypatch):
    observed = {}

    def fake_popen(args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)

    result = system_control._launch_app("terminal", SimpleNamespace())

    assert result == {"pid": 42, "how": "interactive_terminal"}
    assert observed["args"] == ["wt.exe"]
    assert observed["kwargs"]["shell"] is False
    assert "creationflags" not in observed["kwargs"]


def test_resolved_application_launch_is_hidden(monkeypatch):
    observed = {}
    registrations = []
    target = SimpleNamespace(kind="app", value="C:\\Tools\\example.exe", name="Example")
    ctx = SimpleNamespace(
        registry=SimpleNamespace(register=lambda *args, **kwargs: registrations.append((args, kwargs)))
    )

    def fake_popen(args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(system_control, "_matching_process_ids", lambda _value: set())
    monkeypatch.setattr(
        system_control, "_verify_launched_app",
        lambda _target, _hwnds, _pids: (84, 1001, "Example"),
    )

    result = system_control._launch_resolved(target, ctx)

    assert result == "Opening Example."
    assert observed["args"] == ["C:\\Tools\\example.exe"]
    assert observed["kwargs"]["shell"] is False
    assert observed["kwargs"].get("creationflags", 0) == _expected_hidden_flags(system_control)
    assert registrations


def test_redirected_application_registers_verified_window_pid(monkeypatch):
    registrations = []
    target = SimpleNamespace(
        kind="app", value="C:\\Windows\\System32\\notepad.exe", name="notepad",
    )
    ctx = SimpleNamespace(
        registry=SimpleNamespace(register=lambda *args, **kwargs: registrations.append((args, kwargs)))
    )

    monkeypatch.setattr(system_control.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(system_control, "_matching_process_ids", lambda _value: {21})
    monkeypatch.setattr(
        system_control, "_verify_launched_app",
        lambda _target, _hwnds, _pids: (99, 1200, "Untitled - Notepad"),
    )

    assert system_control._launch_resolved(target, ctx) == "Opening notepad."
    _, metadata = registrations[0]
    assert metadata["pid"] == 99
    assert metadata["hwnd"] == 1200
    assert metadata["window_title"] == "Untitled - Notepad"
    assert metadata["extra"]["launcher_pid"] == 42
    assert metadata["extra"]["verified_window"] is True
    assert metadata["extra"]["terminate_pid_on_close"] is True


def test_application_window_verification_ignores_hidden_launcher(monkeypatch):
    hidden = SimpleNamespace(title="Calculator", _hWnd=1001)
    visible = SimpleNamespace(title="Calculator", _hWnd=1002)
    monkeypatch.setattr("pygetwindow.getAllWindows", lambda: [hidden, visible])
    monkeypatch.setattr(system_control, "_matching_process_ids", lambda _value: {21, 22})
    monkeypatch.setattr(system_control, "_window_pid", lambda hwnd: {1001: 21, 1002: 22}[hwnd])
    monkeypatch.setattr(system_control, "_effective_window_pid", lambda _hwnd, pid: pid)
    monkeypatch.setattr(system_control, "_native_window_visible", lambda hwnd: hwnd == 1002)

    target = SimpleNamespace(value="calc.exe", name="Calculator")
    assert system_control._verify_launched_app(target, set(), set(), timeout=0.1) == (
        22, 1002, "Calculator",
    )


def test_application_window_verification_uses_hosted_app_pid(monkeypatch):
    window = SimpleNamespace(title="Calculator", _hWnd=1002)
    monkeypatch.setattr("pygetwindow.getAllWindows", lambda: [window])
    monkeypatch.setattr(system_control, "_matching_process_ids", lambda _value: set())
    monkeypatch.setattr(system_control, "_window_pid", lambda _hwnd: 30)
    monkeypatch.setattr(system_control, "_effective_window_pid", lambda _hwnd, _pid: 31)
    monkeypatch.setattr(system_control, "_native_window_visible", lambda _hwnd: True)

    target = SimpleNamespace(value="calc.exe", name="Calculator")
    assert system_control._verify_launched_app(target, set(), set(), timeout=0.1) == (
        31, 1002, "Calculator",
    )


def test_unverified_application_launch_is_not_registered(monkeypatch):
    registrations = []
    target = SimpleNamespace(kind="app", value="missing.exe", name="Missing")
    ctx = SimpleNamespace(
        registry=SimpleNamespace(register=lambda *args, **kwargs: registrations.append((args, kwargs)))
    )
    monkeypatch.setattr(system_control.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(system_control, "_matching_process_ids", lambda _value: set())
    monkeypatch.setattr(system_control, "_verify_launched_app", lambda *_args: None)

    assert system_control._launch_resolved(target, ctx) is None
    assert registrations == []


def test_folder_uses_shell_handoff_and_registers_verified_window(monkeypatch, tmp_path):
    registrations = []
    folder = tmp_path / "Downloads"
    folder.mkdir()
    target = SimpleNamespace(kind="folder", value=str(folder), name="Downloads")
    ctx = SimpleNamespace(
        registry=SimpleNamespace(
            register=lambda *args, **kwargs: registrations.append((args, kwargs))
        )
    )

    opened = []

    def fake_popen(args, **kwargs):
        opened.append((args, kwargs))
        return Process()

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        system_control,
        "_find_new_folder_window",
        lambda _path, _existing: (84, 1001, "Downloads - File Explorer"),
    )

    assert system_control._launch_resolved(target, ctx) == "Opening the folder Downloads."
    assert opened[0][0] == ["explorer.exe", str(folder)]
    assert opened[0][1]["shell"] is False
    assert opened[0][1].get("creationflags", 0) == _expected_hidden_flags(system_control)
    _, metadata = registrations[0]
    assert metadata["pid"] == 84
    assert metadata["hwnd"] == 1001


def test_generic_new_explorer_window_is_verified_by_process(monkeypatch, tmp_path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    monkeypatch.setattr(
        system_control,
        "_native_window_snapshot",
        lambda: [(1001, 84, "File Explorer")],
    )
    monkeypatch.setattr(system_control, "_native_process_name", lambda pid: "explorer.exe")
    monkeypatch.setattr(
        system_control,
        "_matching_process_ids",
        lambda _name: (_ for _ in ()).throw(AssertionError("psutil path used")),
    )

    assert system_control._find_new_folder_window(folder, set(), timeout=0.1) == (
        84, 1001, "File Explorer",
    )


def test_generic_new_non_explorer_window_is_rejected(monkeypatch, tmp_path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    monkeypatch.setattr(
        system_control,
        "_native_window_snapshot",
        lambda: [(1001, 84, "File Explorer")],
    )
    monkeypatch.setattr(system_control, "_native_process_name", lambda pid: "notepad.exe")

    assert system_control._find_new_folder_window(folder, set(), timeout=0.1) is None


def test_coder_vscode_fallback_is_hidden(monkeypatch, tmp_path):
    observed = {}

    class Llm:
        available = True

        def quick_json(self, _prompt, max_tokens):
            return {"files": [{"path": "README.md", "content": "hello"}]}

    ctx = SimpleNamespace(
        registry=SimpleNamespace(register=lambda *args, **kwargs: None),
        llm=Llm(),
        speaker=SimpleNamespace(speak=lambda _text: None),
    )

    def fake_which(name):
        if name == "codex":
            return None
        if name == "code":
            return "code"
        return None

    def fake_popen(args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(coder.Config, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(coder.shutil, "which", fake_which)
    monkeypatch.setattr(coder.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(coder, "CODER_PROMPT", "Build: {description}")

    result = coder.build_app("tiny demo", ctx)

    assert result.startswith("Built 1 file")
    assert observed["args"] == ["code", "."]
    assert observed["kwargs"]["shell"] is False
    assert observed["kwargs"].get("creationflags", 0) == _expected_hidden_flags(coder)
