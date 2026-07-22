"""Windows GUI helpers must not flash a terminal for background work."""
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
    monkeypatch.setattr(system_control.time, "sleep", lambda _seconds: None)

    result = system_control._launch_resolved(target, ctx)

    assert result == "Opening Example."
    assert observed["args"] == ["C:\\Tools\\example.exe"]
    assert observed["kwargs"]["shell"] is False
    assert observed["kwargs"].get("creationflags", 0) == _expected_hidden_flags(system_control)
    assert registrations


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
