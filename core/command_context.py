"""Compact, non-secret context shared by typed and voice command routing."""
from __future__ import annotations


CONTEXT_KEY = "command_context"
FIELDS = (
    "current_application", "current_document", "current_folder",
    "current_browser", "current_tab", "current_research_topic",
    "current_task", "pending_save_request", "pending_confirmation",
    "last_generated_output",
)


def snapshot(state):
    if not isinstance(state, dict):
        return {field: "" for field in FIELDS}
    current = state.setdefault(CONTEXT_KEY, {})
    return {field: current.get(field, "") for field in FIELDS}


def record_result(state, intent, result):
    """Update references only after a command reports a usable result."""
    if not isinstance(state, dict) or not isinstance(intent, dict):
        return
    message = str(result or "")
    low_result = message.lower()
    if any(marker in low_result for marker in (
        "couldn't", "could not", "can't ", "failed", "denied", "unavailable",
        "not registered", "not saved", "not open",
    )):
        return
    current = state.setdefault(CONTEXT_KEY, {})
    skill = str(intent.get("skill") or "")
    params = intent.get("params") or {}
    target = str(params.get("target") or "")

    if skill in {"app.open", "app.open_app"}:
        current["current_application"] = target
    elif skill == "app.open_folder":
        current["current_folder"] = target
        current["current_application"] = "File Explorer"
    elif skill.startswith("office_word.") or skill.startswith("word."):
        current["current_application"] = "Microsoft Word"
        current["current_document"] = str(params.get("topic") or "Word document")
    elif skill.startswith("excel.") or skill == "office.create_spreadsheet":
        current["current_application"] = "Microsoft Excel"
    elif skill.startswith("ppt.") or skill == "office.create_presentation":
        current["current_application"] = "Microsoft PowerPoint"

    if skill.startswith("research.") or skill == "office_word.create_research_document":
        topic = str(params.get("topic") or "").strip()
        if topic:
            current["current_research_topic"] = topic
            current["current_task"] = f"Research: {topic}"

    if skill.startswith("browser.") or skill.startswith("web."):
        destination = str(params.get("destination") or params.get("site") or "browser")
        current["current_browser"] = str(params.get("browser") or "chrome")
        current["current_tab"] = destination

    if skill == "app.close" and target:
        if target == "__recent_folder__":
            current["current_folder"] = ""
            if str(current.get("current_application") or "").lower() == "file explorer":
                current["current_application"] = ""
        elif target.lower() in str(current.get("current_application") or "").lower():
            current["current_application"] = ""
    elif skill == "browser.close":
        current["current_browser"] = ""
        current["current_tab"] = ""
    elif skill == "browser.close_tab":
        current["current_tab"] = ""

    if skill == "task.cancel" or skill == "system.emergency_stop":
        current["current_task"] = ""
