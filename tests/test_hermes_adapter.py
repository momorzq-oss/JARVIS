import pytest

from brain.hermes_adapter import HermesAdapter, HermesAdapterError


def test_disabled_adapter_does_not_run_process():
    with pytest.raises(HermesAdapterError, match="disabled"):
        HermesAdapter(enabled=False).diagnostic()


def test_adapter_rejects_planning_when_disabled():
    with pytest.raises(HermesAdapterError, match="disabled"):
        HermesAdapter(enabled=False, mode="cli").plan({})


def test_adapter_rejects_arbitrary_cli_command():
    with pytest.raises(HermesAdapterError, match="unsupported"):
        HermesAdapter(enabled=True, mode="cli").diagnostic("gateway")


def test_pilot_command_forces_safe_mode_and_zero_toolset(monkeypatch, tmp_path):
    runtime = tmp_path / "hermes" / "hermes-agent"
    python = runtime / "venv" / "Scripts" / "python.exe"
    launcher = runtime / "hermes"
    python.parent.mkdir(parents=True)
    python.write_text("")
    launcher.write_text("")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    command = HermesAdapter(enabled=True, mode="cli")._pilot_command("plan")
    assert "--safe-mode" in command
    assert command[command.index("--toolsets") + 1] == "context_engine"
