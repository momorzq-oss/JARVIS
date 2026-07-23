import json

import pytest

from brain.hermes_adapter import HermesAdapter, HermesAdapterError
from brain.hermes_protocol import HermesPlanRequest


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
    assert command[2] == "chat"
    assert "--quiet" in command
    assert "--safe-mode" in command
    assert command[command.index("--toolsets") + 1] == "context_engine"
    assert command[command.index("--max-turns") + 1] == "1"
    assert command[command.index("--source") + 1] == "tool"
    assert command[command.index("--query") + 1] == "plan"


def test_plan_decodes_official_quiet_output_as_utf8(monkeypatch):
    request = HermesPlanRequest("goal", "request", [], {}, [], {}, [])
    payload = {
        "protocol_version": "1.0", "task_id": request.task_id,
        "status": "planned", "summary": "Safe plan.", "steps": [],
    }
    observed = {}

    class Completed:
        returncode = 0
        stdout = json.dumps(payload, ensure_ascii=False)
        stderr = ""

    def run(*args, **kwargs):
        observed.update(kwargs)
        return Completed()

    adapter = HermesAdapter(enabled=True, mode="cli")
    monkeypatch.setattr(adapter, "_pilot_command", lambda _prompt: ["hermes"])
    monkeypatch.setattr("brain.hermes_adapter.subprocess.run", run)

    assert adapter.plan(request)["summary"] == "Safe plan."
    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "replace"
