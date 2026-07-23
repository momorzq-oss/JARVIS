import pytest
from types import SimpleNamespace

from brain.hermes_orchestrator import HermesOrchestrator


def test_orchestrator_requires_matching_task_id():
    orchestrator = HermesOrchestrator()
    request = orchestrator.prepare_request("goal", "request", [])
    payload = {"protocol_version": "1.0", "task_id": "wrong", "status": "planned", "summary": "none", "steps": []}
    with pytest.raises(ValueError, match="task_id"):
        orchestrator.accept_plan(request, payload)


def test_orchestrator_exposes_only_healthy_registered_pilot_subset():
    records = [
        SimpleNamespace(
            capability_id="browser.read_page", status="WORKING", connected=True,
            permission="SAFE_READ", risk="low",
        ),
        SimpleNamespace(
            capability_id="office_word.insert_text", status="REQUIRES_LOGIN",
            connected=False, permission="OFFICE_EDIT", risk="low",
        ),
        SimpleNamespace(
            capability_id="email.send", status="WORKING", connected=True,
            permission="EMAIL_SEND", risk="high",
        ),
    ]
    registry = SimpleNamespace(snapshot=lambda: records)
    orchestrator = HermesOrchestrator(capability_registry=registry)

    request = orchestrator.prepare_request("goal", "request")

    assert request.available_capabilities == [{
        "capability_id": "browser.read_page", "skill": "browser",
        "operation": "read_page", "permission_scope": "SAFE_READ",
        "risk_level": "low",
    }]


def test_orchestrator_requested_subset_cannot_expand_registry_exposure():
    records = [
        SimpleNamespace(
            capability_id=capability_id, status="WORKING", connected=True,
            permission="SAFE_READ", risk="low",
        )
        for capability_id in ("browser.read_page", "task.pause")
    ]
    registry = SimpleNamespace(snapshot=lambda: records)
    orchestrator = HermesOrchestrator(capability_registry=registry)

    request = orchestrator.prepare_request(
        "goal", "request", [{"capability_id": "task.pause"}],
    )

    assert [item["capability_id"] for item in request.available_capabilities] == [
        "task.pause",
    ]


def test_orchestrator_rejects_plan_capability_not_in_exact_request():
    orchestrator = HermesOrchestrator()
    request = orchestrator.prepare_request("goal", "request", [])
    payload = {
        "protocol_version": "1.0", "task_id": request.task_id,
        "status": "planned", "summary": "Expanded plan.",
        "steps": [{
            "step_id": "step-1", "capability_id": "browser.read_page",
            "skill": "browser", "operation": "read_page", "parameters": {},
            "permission_scope": "SAFE_READ", "risk_level": "low",
            "requires_confirmation": False, "reversible": True,
            "success_condition": "Page read", "failure_strategy": "stop",
        }],
    }

    with pytest.raises(ValueError, match="blocked or unknown capability"):
        orchestrator.accept_plan(request, payload)
    assert orchestrator.tasks.list() == []


def _one_step_plan(request, failure_strategy="stop"):
    return {
        "protocol_version": "1.0", "task_id": request.task_id,
        "status": "planned", "summary": "Read one public page.",
        "steps": [{
            "step_id": "step-1", "capability_id": "browser.read_page",
            "skill": "browser", "operation": "read_page", "parameters": {},
            "permission_scope": "SAFE_READ", "risk_level": "low",
            "requires_confirmation": False, "reversible": True,
            "success_condition": "Page text returned",
            "failure_strategy": failure_strategy,
        }],
    }


def _browser_registry():
    record = SimpleNamespace(
        capability_id="browser.read_page", status="WORKING", connected=True,
        permission="SAFE_READ", risk="low",
    )
    return SimpleNamespace(snapshot=lambda: [record])


def test_approved_plan_runs_only_through_verified_executor_result():
    orchestrator = HermesOrchestrator(capability_registry=_browser_registry())
    request = orchestrator.prepare_request("goal", "request")

    _plan, task, results = orchestrator.run_approved_plan(
        request, _one_step_plan(request),
        lambda step: {"ok": True, "result": "public text"}, approved=True,
    )

    assert task.status == "COMPLETED"
    assert task.progress == 1.0
    assert task.capabilities_used == ["browser.read_page"]
    assert task.confirmations == ["approved_once"]
    assert results == ["public text"]


def test_denied_plan_never_calls_executor():
    orchestrator = HermesOrchestrator(capability_registry=_browser_registry())
    request = orchestrator.prepare_request("goal", "request")

    _plan, task, results = orchestrator.run_approved_plan(
        request, _one_step_plan(request),
        lambda _step: (_ for _ in ()).throw(AssertionError("denied plan executed")),
        approved=False,
    )

    assert task.status == "CANCELLED"
    assert task.confirmations == ["denied"]
    assert results == []


def test_unverified_executor_result_fails_task_without_progress():
    orchestrator = HermesOrchestrator(capability_registry=_browser_registry())
    request = orchestrator.prepare_request("goal", "request")

    _plan, task, results = orchestrator.run_approved_plan(
        request, _one_step_plan(request), lambda _step: "claimed success",
        approved=True,
    )

    assert task.status == "FAILED"
    assert task.current_step == 0
    assert "verified status" in task.last_error
    assert results == []
