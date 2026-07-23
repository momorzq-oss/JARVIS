"""Strict, data-only protocol between JARVIS and an optional Hermes planner."""
from __future__ import annotations

import dataclasses
import json
import re
import uuid
from typing import Any

from config import Config

PROTOCOL_VERSION = "1.0"
PILOT_CAPABILITIES = frozenset({
    "research.search_web", "research.read_source", "research.summarize_sources",
    "news.fetch", "browser.open_website", "browser.search", "browser.read_page",
    "files.create_temp_folder", "files.create_temp_file", "files.read_temp_file",
    "office_word.create_document", "office_word.insert_text", "office_word.apply_heading",
    "office_word.save_document", "windows.open_application", "windows.open_folder",
    "windows.focus_window", "task.pause", "task.resume", "task.cancel",
    "speech.speak_summary",
})
_FORBIDDEN = re.compile(r"(?:\bpowershell\b|\bcmd(?:\.exe)?\b|\bbash\b|\bpython(?:\.exe)?\b|\beval\s*\(|\bexec\s*\(|[;&|`]|\x00)", re.I)


class HermesProtocolError(ValueError):
    pass


def _reject_executable_text(value: Any) -> None:
    if isinstance(value, str) and _FORBIDDEN.search(value):
        raise HermesProtocolError("executable or shell text is forbidden")
    if isinstance(value, dict):
        for item in value.values():
            _reject_executable_text(item)
    if isinstance(value, list):
        for item in value:
            _reject_executable_text(item)


@dataclasses.dataclass(frozen=True)
class HermesPlanRequest:
    goal: str
    user_request: str
    available_capabilities: list[dict]
    permission_state: dict
    active_sessions: list[dict]
    relevant_context: dict
    constraints: list[str]
    task_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "protocol_version": PROTOCOL_VERSION, "task_id": self.task_id,
            "goal": self.goal, "user_request": self.user_request,
            "execution_policy": {"max_steps": Config.HERMES_MAX_STEPS,
                "max_retries": Config.HERMES_MAX_RETRIES,
                "background_allowed": Config.HERMES_BACKGROUND_TASKS_ENABLED,
                "schedule_allowed": Config.HERMES_SCHEDULING_ENABLED,
                "learning_allowed": Config.HERMES_LEARNING_ENABLED},
            "available_capabilities": self.available_capabilities,
            "permission_state": self.permission_state,
            "active_sessions": self.active_sessions,
            "relevant_context": self.relevant_context,
            "constraints": self.constraints,
        }


def validate_plan(payload: Any, allowed_capabilities=PILOT_CAPABILITIES) -> dict:
    """Validate an untrusted planner response; never execute it."""
    if not isinstance(payload, dict):
        raise HermesProtocolError("plan must be a JSON object")
    required = {"protocol_version", "task_id", "status", "summary", "steps"}
    if set(payload) != required:
        raise HermesProtocolError("plan fields do not match protocol")
    if payload["protocol_version"] != PROTOCOL_VERSION:
        raise HermesProtocolError("unsupported protocol version")
    if payload["status"] != "planned" or not isinstance(payload["summary"], str):
        raise HermesProtocolError("plan must have planned status and text summary")
    if (not isinstance(payload["steps"], list) or not payload["steps"]
            or len(payload["steps"]) > Config.HERMES_MAX_STEPS):
        raise HermesProtocolError("invalid number of steps")
    ids = set()
    clean_steps = []
    expected = {"step_id", "capability_id", "skill", "operation", "parameters",
                "permission_scope", "risk_level", "requires_confirmation", "reversible",
                "success_condition", "failure_strategy"}
    for step in payload["steps"]:
        if not isinstance(step, dict) or set(step) != expected:
            raise HermesProtocolError("step fields do not match protocol")
        cap = step["capability_id"]
        if cap not in allowed_capabilities:
            raise HermesProtocolError(f"blocked or unknown capability: {cap}")
        if cap != f"{step['skill']}.{step['operation']}":
            raise HermesProtocolError("capability, skill, and operation disagree")
        if not isinstance(step["parameters"], dict) or not step["permission_scope"]:
            raise HermesProtocolError("parameters and permission scope are required")
        if step["risk_level"] not in {"low", "medium", "high", "critical"}:
            raise HermesProtocolError("invalid risk level")
        if not isinstance(step["requires_confirmation"], bool) or not isinstance(step["reversible"], bool):
            raise HermesProtocolError("invalid safety metadata")
        if step["risk_level"] in {"high", "critical"} and not step["requires_confirmation"]:
            raise HermesProtocolError("high-risk steps require confirmation")
        if step["failure_strategy"] not in {"stop", "retry", "rollback"}:
            raise HermesProtocolError("invalid failure strategy")
        if not isinstance(step["step_id"], str) or not step["step_id"] or step["step_id"] in ids:
            raise HermesProtocolError("step ids must be unique")
        _reject_executable_text(step)
        ids.add(step["step_id"])
        clean_steps.append(dict(step))
    _reject_executable_text(payload["summary"])
    return {"protocol_version": PROTOCOL_VERSION, "task_id": str(payload["task_id"]),
            "status": "planned", "summary": payload["summary"].strip(), "steps": clean_steps}


def parse_plan_json(raw: str, allowed_capabilities=PILOT_CAPABILITIES) -> dict:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HermesProtocolError("malformed JSON plan") from exc
    return validate_plan(value, allowed_capabilities)
