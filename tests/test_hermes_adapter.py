import json
import subprocess
import threading
import time

import pytest

from brain.hermes_adapter import (
    HermesAdapter, HermesAdapterError, _session_failure_detail,
)
from brain.hermes_protocol import HermesPlanRequest


def _valid_safe_plan_fixture():
    request = HermesPlanRequest(
        "goal", "request",
        [{
            "capability_id": "research.search_web",
            "permission_scope": "BROWSER_NAVIGATE", "risk_level": "low",
        }],
        {}, [], {}, [],
    )
    payload = {
        "protocol_version": "1.0", "task_id": request.task_id,
        "status": "planned", "summary": "Safe plan.",
        "steps": [{
            "step_id": "step-1", "capability_id": "research.search_web",
            "skill": "research", "operation": "search_web",
            "parameters": {"query": "public topic"},
            "permission_scope": "BROWSER_NAVIGATE", "risk_level": "low",
            "requires_confirmation": False, "reversible": True,
            "success_condition": "results", "failure_strategy": "stop",
        }],
    }
    return request, payload


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


def test_session_failure_detail_reports_provider_error_without_private_ids(
    monkeypatch, tmp_path,
):
    session_id = "20260723_122947_3428f8"
    sessions = tmp_path / "hermes" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / f"request_dump_{session_id}_20260723_123014_721150.json").write_text(
        json.dumps({
            "error": {
                "message": "private-user-id-must-not-appear",
                "status_code": 429,
                "body": {
                    "message": "Provider returned error",
                    "code": 429,
                    "metadata": {
                        "raw": "The selected model is temporarily rate-limited upstream.",
                        "provider_name": "Example Provider",
                    },
                },
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    detail = _session_failure_detail(f"session_id: {session_id}")

    assert detail == (
        "Hermes provider error 429: The selected model is temporarily "
        "rate-limited upstream. (upstream: Example Provider)"
    )
    assert "private-user-id" not in detail


def test_plan_decodes_official_quiet_output_as_utf8(monkeypatch):
    request, payload = _valid_safe_plan_fixture()
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


def test_plan_prompt_contains_the_exact_response_contract(monkeypatch):
    request, payload = _valid_safe_plan_fixture()
    observed = {}

    class Process:
        pid = -1
        returncode = 0

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            return json.dumps(payload), ""

    adapter = HermesAdapter(enabled=True, mode="cli")
    def pilot_command(prompt):
        observed["prompt"] = prompt
        return ["hermes"]

    monkeypatch.setattr(adapter, "_pilot_command", pilot_command)
    monkeypatch.setattr(
        "brain.hermes_adapter.subprocess.Popen", lambda *args, **kwargs: Process(),
    )

    adapter.plan(request)

    prompt = observed["prompt"]
    assert "exactly these five top-level keys" in prompt
    assert '"status": "planned"' in prompt
    assert '"success_condition": "verifiable result"' in prompt
    assert "Copy task_id exactly" in prompt


def test_plan_rejects_pilot_capability_not_supplied_in_request(monkeypatch):
    request = HermesPlanRequest(
        "goal", "request",
        [{"capability_id": "research.search_web",
          "permission_scope": "BROWSER_NAVIGATE", "risk_level": "low"}],
        {}, [], {}, [],
    )
    payload = {
        "protocol_version": "1.0", "task_id": request.task_id,
        "status": "planned", "summary": "Unsafe expansion.",
        "steps": [{
            "step_id": "step-1", "capability_id": "browser.search",
            "skill": "browser", "operation": "search", "parameters": {},
            "permission_scope": "BROWSER_NAVIGATE", "risk_level": "low",
            "requires_confirmation": False, "reversible": True,
            "success_condition": "Results are visible", "failure_strategy": "stop",
        }],
    }
    adapter = HermesAdapter(enabled=True, mode="cli")
    monkeypatch.setattr(adapter, "_pilot_command", lambda _prompt: ["hermes"])
    monkeypatch.setattr(
        adapter, "_run_cancellable",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["hermes"], 0, json.dumps(payload), "",
        ),
    )

    with pytest.raises(ValueError, match="blocked or unknown capability"):
        adapter.plan(request)


def test_plan_rejects_permission_metadata_different_from_supplied_capability(monkeypatch):
    request = HermesPlanRequest(
        "goal", "request",
        [{"capability_id": "research.search_web",
          "permission_scope": "BROWSER_NAVIGATE", "risk_level": "low"}],
        {}, [], {}, [],
    )
    payload = {
        "protocol_version": "1.0", "task_id": request.task_id,
        "status": "planned", "summary": "Mismatched metadata.",
        "steps": [{
            "step_id": "step-1", "capability_id": "research.search_web",
            "skill": "research", "operation": "search_web", "parameters": {},
            "permission_scope": "SAFE_WRITE", "risk_level": "low",
            "requires_confirmation": False, "reversible": True,
            "success_condition": "Results are visible", "failure_strategy": "stop",
        }],
    }
    adapter = HermesAdapter(enabled=True, mode="cli")
    monkeypatch.setattr(adapter, "_pilot_command", lambda _prompt: ["hermes"])
    monkeypatch.setattr(
        adapter, "_run_cancellable",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["hermes"], 0, json.dumps(payload), "",
        ),
    )

    with pytest.raises(HermesAdapterError, match="permission scope contradicts"):
        adapter.plan(request)


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
