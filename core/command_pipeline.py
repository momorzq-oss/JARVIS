"""One authoritative, side-effect-free route selector for every input source."""
from __future__ import annotations

from brain.router import fast_lane
from core.command_text import cleanup_command
from core.planner import plan_command


PREEMPT_PENDING_PREFIXES = (
    "system.", "task.", "app.", "window.", "browser.", "web.",
    "office.", "office_word.", "word.", "excel.", "ppt.",
    "university.",
)


def select_route(text, ctx, source="typed"):
    cleaned = cleanup_command(text)
    route = {
        "raw_input": str(text or ""),
        "cleaned_input": cleaned,
        "source": source,
        "route_type": "empty",
        "selected_engine": "none",
        "intent": None,
        "plan": [],
    }
    if not cleaned:
        return route

    state = getattr(ctx, "state", {})
    intent = fast_lane(cleaned, state)
    pending = getattr(ctx, "pending", None)
    skill = str((intent or {}).get("skill") or "")
    pending_kind = str((pending or {}).get("kind") or "")
    close_awaiting_save = (
        pending_kind == "save_document" and skill == "app.close"
    )

    # Immediate local controls and concrete PC actions remain reachable even
    # while a research/save workflow is pending.
    if intent is not None and (
        pending is None or (
            skill.startswith(PREEMPT_PENDING_PREFIXES)
            and not close_awaiting_save
        )
    ):
        route.update(
            route_type="intent", selected_engine="deterministic",
            intent=intent,
        )
        return route

    if pending is not None:
        route.update(
            route_type="pending", selected_engine="contextual_pending",
            pending_kind=pending_kind or "unknown",
        )
        return route

    plan = plan_command(cleaned)
    if plan:
        route.update(
            route_type="plan", selected_engine="deterministic_planner",
            plan=plan,
        )
        return route

    router = getattr(ctx, "router", None)
    intent = router.classify(cleaned) if router is not None else {
        "skill": "chat", "params": {"message": cleaned},
    }
    selected = "local_router"
    if intent.get("skill") == "chat" and getattr(router, "load_error", ""):
        selected = "local_conversation_fallback"
    route.update(route_type="intent", selected_engine=selected, intent=intent)
    return route
