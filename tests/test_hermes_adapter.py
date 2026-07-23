import json
import subprocess
import threading
import time

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


def test_live_adapter_configuration_drives_official_provider_arguments(monkeypatch, tmp_path):
    runtime = tmp_path / "hermes" / "hermes-agent"
    python = runtime / "venv" / "Scripts" / "python.exe"
    launcher = runtime / "hermes"
    python.parent.mkdir(parents=True)
    python.write_text("")
    launcher.write_text("")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    adapter = HermesAdapter(enabled=False, mode="disabled")

    adapter.configure(
        enabled=True, mode="cli", provider="openrouter",
        model="openai/gpt-oss-safeguard-20b", timeout=45,
    )
    command = adapter._pilot_command("plan")

    assert adapter.enabled is True
    assert adapter.timeout == 45
    assert command[command.index("--provider") + 1] == "openrouter"
    assert command[command.index("--model") + 1] == "openai/gpt-oss-safeguard-20b"


def test_adapter_rejects_presentation_only_runtime_mode():
    adapter = HermesAdapter(enabled=False, mode="disabled")
    with pytest.raises(HermesAdapterError, match="unsupported"):
        adapter.configure(
            enabled=True, mode="managed", provider="openrouter", model="model",
        )


def test_plan_decodes_official_quiet_output_as_utf8(monkeypatch):
    request = HermesPlanRequest("goal", "request", [], {}, [], {}, [])
    payload = {
        "protocol_version": "1.0", "task_id": request.task_id,
        "status": "planned", "summary": "Safe plan.", "steps": [],
    }
    observed = {}

    class Process:
        pid = -1
        returncode = 0

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            return json.dumps(payload, ensure_ascii=False), ""

    def popen(*args, **kwargs):
        observed.update(kwargs)
        return Process()

    adapter = HermesAdapter(enabled=True, mode="cli")
    monkeypatch.setattr(adapter, "_pilot_command", lambda _prompt: ["hermes"])
    monkeypatch.setattr("brain.hermes_adapter.subprocess.Popen", popen)

    assert adapter.plan(request)["summary"] == "Safe plan."
    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "replace"


def test_active_plan_process_is_cancelled_and_cleared(monkeypatch):
    request = HermesPlanRequest("goal", "request", [], {}, [], {}, [])
    started = threading.Event()

    class BlockingProcess:
        pid = -1

        def __init__(self):
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            started.set()
            if self.returncode is None:
                raise subprocess.TimeoutExpired("hermes", timeout)
            return "", ""

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    process = BlockingProcess()
    adapter = HermesAdapter(enabled=True, mode="cli", timeout=5)
    monkeypatch.setattr(adapter, "_pilot_command", lambda _prompt: ["hermes"])
    monkeypatch.setattr("brain.hermes_adapter.subprocess.Popen", lambda *a, **k: process)
    errors = []

    worker = threading.Thread(
        target=lambda: _capture_error(errors, lambda: adapter.plan(request)), daemon=True,
    )
    worker.start()
    assert started.wait(1)
    assert adapter.running
    assert adapter.cancel()
    worker.join(2)

    assert not worker.is_alive()
    assert process.terminated
    assert not adapter.running
    assert len(errors) == 1
    assert isinstance(errors[0], HermesAdapterError)
    assert "cancelled" in str(errors[0]).lower()


def test_plan_timeout_terminates_owned_process(monkeypatch):
    request = HermesPlanRequest("goal", "request", [], {}, [], {}, [])

    class BlockingProcess:
        pid = -1
        returncode = None
        terminated = False

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired("hermes", timeout)

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    process = BlockingProcess()
    clock = iter((0.0, 2.0))
    adapter = HermesAdapter(enabled=True, mode="cli", timeout=1)
    monkeypatch.setattr(adapter, "_pilot_command", lambda _prompt: ["hermes"])
    monkeypatch.setattr("brain.hermes_adapter.subprocess.Popen", lambda *a, **k: process)
    monkeypatch.setattr("brain.hermes_adapter.time.monotonic", lambda: next(clock))

    with pytest.raises(HermesAdapterError, match="timed out"):
        adapter.plan(request)

    assert process.terminated
    assert not adapter.running


def _capture_error(errors, callback):
    try:
        callback()
    except Exception as exc:
        errors.append(exc)
