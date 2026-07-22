import pytest

from brain.hermes_orchestrator import HermesOrchestrator


def test_orchestrator_requires_matching_task_id():
    orchestrator = HermesOrchestrator()
    request = orchestrator.prepare_request("goal", "request", [])
    payload = {"protocol_version": "1.0", "task_id": "wrong", "status": "planned", "summary": "none", "steps": []}
    with pytest.raises(ValueError, match="task_id"):
        orchestrator.accept_plan(request, payload)
