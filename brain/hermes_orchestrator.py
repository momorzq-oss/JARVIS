"""JARVIS-owned validation boundary for optional Hermes plans."""
from __future__ import annotations

from config import Config

from .hermes_protocol import PILOT_CAPABILITIES, HermesPlanRequest, validate_plan
from .hermes_task_manager import HermesTaskManager


class HermesOrchestrator:
    def __init__(self, task_manager=None, capability_registry=None):
        self.tasks = task_manager or HermesTaskManager()
        self.registry = capability_registry

    def eligible_capabilities(self, requested=None):
        """Return only healthy, connected registry records in the pilot set."""
        requested_ids = None
        if requested is not None:
            requested_ids = {
                str(item.get("capability_id") or item.get("id") or "").strip()
                for item in requested if isinstance(item, dict)
            }
            requested_ids.discard("")
        records = self.registry.snapshot() if self.registry is not None else []
        eligible = []
        for record in records:
            capability_id = str(getattr(record, "capability_id", "") or "").strip()
            if capability_id not in PILOT_CAPABILITIES:
                continue
            if requested_ids is not None and capability_id not in requested_ids:
                continue
            status = str(getattr(record, "status", "") or "").upper()
            connected = bool(getattr(record, "connected", False))
            if status not in {"WORKING", "CONNECTED"} or not connected:
                continue
            skill, operation = capability_id.split(".", 1)
            permission = str(getattr(record, "permission", "") or "").strip()
            risk = str(getattr(record, "risk", "") or "").strip().lower()
            if not permission or permission == "UNASSIGNED":
                continue
            if risk not in {"low", "medium", "high", "critical"}:
                continue
            eligible.append({
                "capability_id": capability_id,
                "skill": skill,
                "operation": operation,
                "permission_scope": permission,
                "risk_level": risk,
            })
        return sorted(eligible, key=lambda item: item["capability_id"])

    def prepare_request(self, goal, user_request, capabilities=None, permission_state=None, sessions=None, context=None):
        eligible = self.eligible_capabilities(capabilities)
        return HermesPlanRequest(goal=str(goal), user_request=str(user_request),
            available_capabilities=eligible, permission_state=permission_state or {},
            active_sessions=sessions or [], relevant_context=context or {},
            constraints=["JARVIS executes all actions", "No shell or code", "Pilot allowlist only"])

    def accept_plan(self, request: HermesPlanRequest, payload: dict, task_id=None):
        supplied = {
            str(item.get("capability_id") or item.get("id") or ""): item
            for item in request.available_capabilities if isinstance(item, dict)
        }
        supplied.pop("", None)
        plan = validate_plan(payload, allowed_capabilities=frozenset(supplied))
        if plan["task_id"] != request.task_id:
            raise ValueError("plan task_id does not match request")
        for step in plan["steps"]:
            capability = supplied[step["capability_id"]]
            if step["permission_scope"] != capability["permission_scope"]:
                raise ValueError("plan permission scope contradicts registry")
            if step["risk_level"] != capability["risk_level"]:
                raise ValueError("plan risk level contradicts registry")
        task = self.tasks.get(task_id) if task_id else self.tasks.create(request.goal)
        if task is None:
            raise ValueError("Hermes task does not exist")
        self.tasks.transition(task.task_id, "WAITING_CONFIRMATION", steps=len(plan["steps"]))
        return plan, self.tasks.get(task.task_id)

    def run_approved_plan(self, request, payload, execute_step, *, approved,
                          task_id=None):
        """Run validated data only through a caller-supplied trusted executor."""
        plan, task = self.accept_plan(request, payload, task_id=task_id)
        decision = "approved_once" if approved else "denied"
        self.tasks.record_confirmation(task.task_id, decision)
        if not approved:
            return plan, self.tasks.cancel(task.task_id), []
        self.tasks.transition(task.task_id, "RUNNING")
        results = []
        for step in plan["steps"]:
            if not self.tasks.wait_until_runnable(task.task_id):
                return plan, self.tasks.get(task.task_id), results
            attempts = 0
            while True:
                try:
                    outcome = execute_step(dict(step))
                    if not isinstance(outcome, dict) or not isinstance(outcome.get("ok"), bool):
                        raise RuntimeError("trusted executor did not return verified status")
                    if not outcome["ok"]:
                        raise RuntimeError(str(outcome.get("error") or "success condition failed"))
                    break
                except Exception as exc:
                    current = self.tasks.get(task.task_id)
                    if current is not None and current.cancellation_token:
                        return plan, current, results
                    if (step["failure_strategy"] == "retry"
                            and attempts < Config.HERMES_MAX_RETRIES):
                        attempts += 1
                        self.tasks.record_retry(task.task_id, str(exc))
                        self.tasks.transition(task.task_id, "RETRYING", error=str(exc))
                        self.tasks.transition(task.task_id, "RUNNING")
                        continue
                    self.tasks.transition(task.task_id, "FAILED", error=str(exc))
                    return plan, self.tasks.get(task.task_id), results
            # Cancellation can win while a bounded trusted operation is in
            # flight. Its late return must not record progress/output or
            # escape as a misleading pipeline error.
            current = self.tasks.get(task.task_id)
            if current is not None and current.cancellation_token:
                return plan, current, results
            try:
                self.tasks.complete_step(
                    task.task_id, step["capability_id"], step["permission_scope"],
                    outcome.get("output_files") or [],
                )
            except RuntimeError:
                current = self.tasks.get(task.task_id)
                if current is not None and current.cancellation_token:
                    return plan, current, results
                raise
            results.append(outcome.get("result"))
        self.tasks.transition(task.task_id, "COMPLETED")
        return plan, self.tasks.get(task.task_id), results
