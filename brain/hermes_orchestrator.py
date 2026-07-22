"""JARVIS-owned validation boundary for optional Hermes plans."""
from __future__ import annotations

from .hermes_protocol import HermesPlanRequest, validate_plan
from .hermes_task_manager import HermesTaskManager


class HermesOrchestrator:
    def __init__(self, task_manager=None):
        self.tasks = task_manager or HermesTaskManager()

    def prepare_request(self, goal, user_request, capabilities, permission_state=None, sessions=None, context=None):
        return HermesPlanRequest(goal=str(goal), user_request=str(user_request),
            available_capabilities=list(capabilities), permission_state=permission_state or {},
            active_sessions=sessions or [], relevant_context=context or {},
            constraints=["JARVIS executes all actions", "No shell or code", "Pilot allowlist only"])

    def accept_plan(self, request: HermesPlanRequest, payload: dict):
        plan = validate_plan(payload)
        if plan["task_id"] != request.task_id:
            raise ValueError("plan task_id does not match request")
        task = self.tasks.create(request.goal)
        self.tasks.transition(task.task_id, "WAITING_CONFIRMATION", steps=len(plan["steps"]))
        return plan, self.tasks.get(task.task_id)
