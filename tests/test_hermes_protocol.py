import pytest

from brain.hermes_protocol import HermesPlanRequest, HermesProtocolError, validate_plan


def _plan(task_id="task-1", capability="research.search_web", parameters=None):
    skill, operation = capability.split(".", 1)
    return {"protocol_version": "1.0", "task_id": task_id, "status": "planned", "summary": "Search public sources.",
        "steps": [{"step_id": "one", "capability_id": capability, "skill": skill, "operation": operation,
                   "parameters": parameters or {"query": "renewable energy"}, "permission_scope": "SAFE_READ",
                   "risk_level": "low", "requires_confirmation": False, "reversible": True,
                   "success_condition": "sources found", "failure_strategy": "stop"}]}


def test_request_has_policy_and_unique_id():
    request = HermesPlanRequest("goal", "request", [], {}, [], {}, [])
    assert request.to_dict()["protocol_version"] == "1.0"
    assert request.task_id


def test_plan_accepts_pilot_capability():
    assert validate_plan(_plan())["steps"][0]["capability_id"] == "research.search_web"


@pytest.mark.parametrize("payload", [_plan(capability="files.delete"), _plan(parameters={"command": "powershell rm"})])
def test_plan_rejects_blocked_capability_and_shell(payload):
    with pytest.raises(HermesProtocolError):
        validate_plan(payload)


def test_plan_rejects_wrong_protocol():
    payload = _plan()
    payload["protocol_version"] = "2.0"
    with pytest.raises(HermesProtocolError, match="protocol"):
        validate_plan(payload)
