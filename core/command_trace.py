"""Redacted developer trace for the shared command route; never executes it."""
from __future__ import annotations

import json

from core.action_manager import ActionManager
from core.command_context import snapshot
from core.command_pipeline import select_route


def build_trace(command, ctx, source="typed"):
    route = select_route(command, ctx, source=source)
    route["contextual_references"] = snapshot(getattr(ctx, "state", {}))
    route["schema_result"] = "not_applicable"
    route["allowlist_result"] = "not_applicable"
    route["permission_scope"] = ""
    route["capability_id"] = ""
    route["dependency_state"] = "unverified"

    candidates = route.get("plan") or ([route.get("intent")] if route.get("intent") else [])
    if candidates:
        intent = candidates[0]
        full_skill = str(intent.get("skill") or "")
        route["capability_id"] = full_skill
        manager = getattr(ctx, "action_manager", None)
        if manager is None:
            manager = ActionManager(type("TraceController", (), {})())
        try:
            action = manager.action_from_intent(intent)
            manager.validate_action(action)
            route["schema_result"] = "valid"
            route["allowlist_result"] = "allowed"
            route["permission_scope"] = action.permission_scope
        except Exception as exc:
            route["schema_result"] = "rejected"
            route["allowlist_result"] = str(exc)

        registry = getattr(getattr(ctx, "assistant_controller", None), "capability_registry", None)
        if registry is not None:
            record = next(
                (item for item in registry.snapshot() if item.capability_id == full_skill),
                None,
            )
            if record is not None:
                route["dependency_state"] = record.status

    # Use the same redactor as audit logging, including any text nested in
    # parameters.  No provider prompt, hidden reasoning, key or token is read.
    redactor = getattr(ctx, "action_manager", None)
    if redactor is None:
        redactor = ActionManager(type("TraceController", (), {})())
    return redactor._redact_sensitive_values(route)


def format_trace(command, ctx, source="typed"):
    return json.dumps(build_trace(command, ctx, source=source), indent=2, ensure_ascii=False)
