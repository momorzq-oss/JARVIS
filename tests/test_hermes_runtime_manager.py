import subprocess

from brain.hermes_runtime_manager import HermesRuntimeManager


def test_official_provider_setup_uses_direct_external_runtime(monkeypatch, tmp_path):
    home = tmp_path / "hermes"
    repo = home / "hermes-agent"
    python = repo / "venv" / "Scripts" / "python.exe"
    launcher = repo / "hermes"
    python.parent.mkdir(parents=True)
    python.write_text("")
    launcher.write_text("")
    observed = {}

    class Process:
        pid = 1234

    def popen(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return Process()

    monkeypatch.setattr(subprocess, "Popen", popen)
    result = HermesRuntimeManager(home=home).open_provider_setup()

    assert result["state"] == "OPENED"
    assert observed["command"] == [str(python), str(launcher), "model"]
    assert observed["shell"] is False
    assert observed["cwd"] == str(repo)


def test_provider_setup_reports_missing_runtime_without_launch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not launch")),
    )

    result = HermesRuntimeManager(home=tmp_path / "missing").open_provider_setup()

    assert result["state"] == "NOT_INSTALLED"
