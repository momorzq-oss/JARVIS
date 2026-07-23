import dataclasses
import json
import os
import re
import time
import uuid
from typing import Any, Dict, Literal, Optional

from config import Config
from voice import audio_log


@dataclasses.dataclass
class Action:
    action_id: str
    skill: str
    operation: str
    parameters: Dict[str, Any]
    permission_scope: Optional[str] = None
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    requires_confirmation: bool = False
    reversible: bool = True
    rollback_action: Optional[str] = None

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, dict):
            raise ValueError("Action payload must be an object")
        expected = {field.name for field in dataclasses.fields(cls)}
        required = expected
        missing = required - payload.keys()
        unknown = payload.keys() - expected
        if missing:
            raise ValueError(f"Missing action fields: {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"Unknown action fields: {', '.join(sorted(unknown))}")
        return cls(**payload)

    def to_dict(self):
        return dataclasses.asdict(self)


class ActionManager:
    INTENT_ALLOWLIST = {
        "app.open": ("DESKTOP_CONTROL", "low"),
        "app.open_app": ("DESKTOP_CONTROL", "low"),
        "app.open_folder": ("SAFE_READ", "low"),
        "app.open_file": ("SAFE_READ", "low"),
        "app.search_file": ("SAFE_READ", "low"),
        "app.close": ("DESKTOP_CONTROL", "medium"),
        "window.front": ("DESKTOP_CONTROL", "low"),
        "window.focus": ("DESKTOP_CONTROL", "low"),
        "window.minimize": ("DESKTOP_CONTROL", "low"),
        "window.maximize": ("DESKTOP_CONTROL", "low"),
        "window.restore": ("DESKTOP_CONTROL", "low"),
        "window.close": ("DESKTOP_CONTROL", "medium"),
        "system.stop_speech": ("DESKTOP_CONTROL", "low"),
        "system.volume": ("DESKTOP_CONTROL", "low"),
        "system.screenshot": ("SAFE_WRITE", "low"),
        "system.lock": ("DESKTOP_CONTROL", "medium"),
        "system.shutdown": ("SYSTEM_POWER", "critical"),
        "system.status": ("SAFE_READ", "low"),
        "system.emergency_stop": ("DESKTOP_CONTROL", "low"),
        "task.pause": ("DESKTOP_CONTROL", "low"),
        "task.resume": ("DESKTOP_CONTROL", "low"),
        "task.cancel": ("DESKTOP_CONTROL", "low"),
        "task.speed": ("DESKTOP_CONTROL", "low"),
        "media.control": ("DESKTOP_CONTROL", "low"),
        "media.play_music": ("BROWSER_NAVIGATE", "low"),
        "browser.open": ("BROWSER_NAVIGATE", "low"),
        "browser.open_site": ("BROWSER_NAVIGATE", "low"),
        "browser.search_youtube": ("BROWSER_NAVIGATE", "low"),
        "browser.search_youtube_and_play": ("BROWSER_NAVIGATE", "low"),
        "browser.close": ("DESKTOP_CONTROL", "medium"),
        "browser.back": ("BROWSER_NAVIGATE", "low"),
        "browser.forward": ("BROWSER_NAVIGATE", "low"),
        "browser.new_tab": ("BROWSER_NAVIGATE", "low"),
        "browser.close_tab": ("DESKTOP_CONTROL", "low"),
        "browser.switch_tab": ("BROWSER_NAVIGATE", "low"),
        "browser.read_page": ("SAFE_READ", "low"),
        "browser.find_on_page": ("SAFE_READ", "low"),
        "browser.fill_form": ("FORM_SUBMIT", "medium"),
        "browser.submit_form": ("FORM_SUBMIT", "high"),
        "browser.download": ("SAFE_WRITE", "medium"),
        "browser.upload": ("FORM_SUBMIT", "high"),
        "browser.youtube_play_first": ("BROWSER_NAVIGATE", "low"),
        "browser.youtube_play_relevant": ("BROWSER_NAVIGATE", "low"),
        "browser.play_video": ("BROWSER_NAVIGATE", "low"),
        "browser.pause_video": ("BROWSER_NAVIGATE", "low"),
        "web.search": ("BROWSER_NAVIGATE", "low"),
        "news.latest": ("SAFE_READ", "low"),
        "news.topic": ("SAFE_READ", "low"),
        "news.more": ("SAFE_READ", "low"),
        "news.save": ("OFFICE_EDIT", "medium"),
        "email.check": ("SAFE_READ", "low"),
        "email.read": ("SAFE_READ", "low"),
        "email.compose": ("EMAIL_DRAFT", "medium"),
        "email.reply": ("EMAIL_DRAFT", "medium"),
        "email.send": ("EMAIL_SEND", "high"),
        "whatsapp.open": ("DESKTOP_CONTROL", "low"),
        "whatsapp.read": ("SAFE_READ", "low"),
        "whatsapp.reply": ("FORM_SUBMIT", "high"),
        "office_word.create_document": ("OFFICE_EDIT", "low"),
        "office_word.create_research_document": ("OFFICE_EDIT", "medium"),
        "office_word.insert_text": ("OFFICE_EDIT", "low"),
        "office_word.save_document": ("SAFE_WRITE", "medium"),
        "word.write": ("OFFICE_EDIT", "medium"),
        "word.continue": ("OFFICE_EDIT", "medium"),
        "excel.create": ("OFFICE_EDIT", "medium"),
        "excel.read": ("SAFE_READ", "low"),
        "ppt.create": ("OFFICE_EDIT", "medium"),
        "office.create_document": ("OFFICE_EDIT", "medium"),
        "office.create_spreadsheet": ("OFFICE_EDIT", "medium"),
        "office.create_presentation": ("OFFICE_EDIT", "medium"),
        "office.save": ("SAFE_WRITE", "low"),
        "office.export": ("SAFE_WRITE", "medium"),
        "website.gmail_search": ("SAFE_READ", "low"),
        "website.gmail_open_latest": ("SAFE_READ", "low"),
        "website.gmail_reply_draft": ("EMAIL_DRAFT", "medium"),
        "website.drive_search": ("SAFE_READ", "low"),
        "website.drive_show_location": ("SAFE_READ", "low"),
        "website.stripe_search_payment": ("SAFE_READ", "low"),
        "desktop.organize": ("FILE_MODIFY", "high"),
        "desktop.undo": ("FILE_MODIFY", "medium"),
        "codex.build": ("SAFE_WRITE", "medium"),
        "research.start": ("BROWSER_NAVIGATE", "low"),
        "research.continue": ("BROWSER_NAVIGATE", "low"),
        "research.finalize": ("SAFE_WRITE", "medium"),
        "research.outline": ("SAFE_READ", "low"),
        "research.create_report": ("SAFE_WRITE", "medium"),
        "research.prepare_report": ("BROWSER_NAVIGATE", "low"),
        "research.gather_report": ("BROWSER_NAVIGATE", "low"),
        "research.draft_report": ("SAFE_WRITE", "medium"),
        "research.finalize_report": ("SAFE_WRITE", "medium"),
        "research.open_report": ("SAFE_READ", "low"),
        "research.search_web": ("BROWSER_NAVIGATE", "low"),
        "research.read_source": ("SAFE_READ", "low"),
        "research.summarize_sources": ("SAFE_READ", "low"),
        "hermes.status": ("SAFE_READ", "low"),
        "hermes.tasks": ("SAFE_READ", "low"),
        "hermes.plan": ("SAFE_READ", "low"),
        "hermes.pause": ("DESKTOP_CONTROL", "low"),
        "hermes.resume": ("DESKTOP_CONTROL", "low"),
        "hermes.cancel": ("DESKTOP_CONTROL", "low"),
        "hermes.approve": ("DESKTOP_CONTROL", "medium"),
        "hermes.deny": ("DESKTOP_CONTROL", "low"),
        "university.assignment": ("OFFICE_EDIT", "medium"),
        "chat": ("SAFE_READ", "low"),
        "smalltalk": ("SAFE_READ", "low"),
    }

    TOOL_ALLOWLIST = {
        "windows": {
            "open_application": "DESKTOP_CONTROL",
            "open_folder": "SAFE_READ",
            "open_file": "SAFE_READ",
            "open_uri": "BROWSER_NAVIGATE",
            "focus_window": "DESKTOP_CONTROL",
            "minimize_window": "DESKTOP_CONTROL",
            "maximize_window": "DESKTOP_CONTROL",
            "restore_window": "DESKTOP_CONTROL",
            "move_window": "DESKTOP_CONTROL",
            "resize_window": "DESKTOP_CONTROL",
            "close_window": "DESKTOP_CONTROL",
            "close_application": "DESKTOP_CONTROL",
            "close_resource": "DESKTOP_CONTROL",
            "close_recent_jarvis_item": "DESKTOP_CONTROL",
            "close_all_jarvis_items": "DESKTOP_CONTROL",
        },
        "office_word": {
            "create_document": "OFFICE_EDIT",
            "create_research_document": "OFFICE_EDIT",
            "insert_text": "OFFICE_EDIT",
            "save_document": "SAFE_WRITE",
        },
        "browser": {
            "open_site": "BROWSER_NAVIGATE",
            "search_youtube": "BROWSER_NAVIGATE",
            "search_youtube_and_play": "BROWSER_NAVIGATE",
            "close": "DESKTOP_CONTROL",
            "back": "BROWSER_NAVIGATE",
            "forward": "BROWSER_NAVIGATE",
            "new_tab": "BROWSER_NAVIGATE",
            "close_tab": "DESKTOP_CONTROL",
            "switch_tab": "BROWSER_NAVIGATE",
            "read_page": "SAFE_READ",
            "find_on_page": "SAFE_READ",
            "fill_form": "FORM_SUBMIT",
            "submit_form": "FORM_SUBMIT",
            "download": "SAFE_WRITE",
            "upload": "FORM_SUBMIT",
            "youtube_play_first": "BROWSER_NAVIGATE",
            "youtube_play_relevant": "BROWSER_NAVIGATE",
            "play_video": "BROWSER_NAVIGATE",
            "pause_video": "BROWSER_NAVIGATE",
        },
        "office": {
            "create_document": "OFFICE_EDIT",
            "create_spreadsheet": "OFFICE_EDIT",
            "create_presentation": "OFFICE_EDIT",
            "save": "SAFE_WRITE",
            "export": "SAFE_WRITE",
        },
        "website": {
            "gmail_search": "SAFE_READ",
            "gmail_open_latest": "SAFE_READ",
            "gmail_reply_draft": "EMAIL_DRAFT",
            "drive_search": "SAFE_READ",
            "drive_show_location": "SAFE_READ",
            "stripe_search_payment": "SAFE_READ",
        },
        "research": {
            "search_web": "BROWSER_NAVIGATE",
            "read_source": "SAFE_READ",
            "summarize_sources": "SAFE_READ",
        },
        "task": {
            "pause": "DESKTOP_CONTROL",
            "resume": "DESKTOP_CONTROL",
            "cancel": "DESKTOP_CONTROL",
            "speed": "DESKTOP_CONTROL",
        },
        "system": {
            "status": "SAFE_READ",
            "control_system_power": "SYSTEM_POWER",
            "emergency_stop": "DESKTOP_CONTROL",
        },
    }

    def __init__(self, controller):
        self.controller = controller

    @staticmethod
    def _redact_text(value):
        text = str(value)
        home = str(os.path.expanduser("~"))
        if home:
            text = re.sub(re.escape(home), "%USERPROFILE%", text, flags=re.I)
        text = re.sub(
            r"\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b",
            r"***@\1", text, flags=re.I,
        )
        text = re.sub(r"\b(?:sk-or-v1-|sk-)[A-Za-z0-9_-]{8,}\b", "[REDACTED]", text)
        text = re.sub(
            r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}\b",
            "[REDACTED]", text,
        )
        text = re.sub(r"(?i)\b(?:bearer|token|password|secret)\s*[:=]\s*\S+", "[REDACTED]", text)
        return text

    def _redact_sensitive_values(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact sensitive information from data for logging/display."""
        redacted_data = data.copy()
        sensitive_keys = (
            "password", "token", "api_key", "secret", "credential", "cookie",
            "authorization", "private_key", "session_key",
        )
        for key, value in list(redacted_data.items()):
            if any(marker in key.lower() for marker in sensitive_keys):
                redacted_data[key] = "[REDACTED]"
            elif isinstance(value, dict):
                redacted_data[key] = self._redact_sensitive_values(value)
            elif isinstance(value, (list, tuple)):
                redacted_data[key] = [
                    self._redact_sensitive_values(item) if isinstance(item, dict)
                    else self._redact_text(item)
                    for item in value
                ]
            elif isinstance(value, str):
                redacted_data[key] = self._redact_text(value)
        if "email" in redacted_data and isinstance(redacted_data["email"], str):
            if "@" in redacted_data["email"]:
                parts = redacted_data["email"].split("@")
                redacted_data["email"] = f"***@{parts[-1]}"
            else:
                redacted_data["email"] = "[REDACTED]"
        for key in ("body", "content", "message", "transcript"):
            if key in redacted_data and isinstance(redacted_data[key], str):
                redacted_data[key] = "[REDACTED CONTENT]"
        return redacted_data

    def audit_log(self, action: Action, outcome: str, message: str = ""):
        """Writes an entry to the audit log file."""
        log_entry = {
            "timestamp": time.time(),
            "action_id": action.action_id,
            "skill": action.skill,
            "operation": action.operation,
            "parameters": self._redact_sensitive_values(action.parameters),
            "permission_scope": action.permission_scope,
            "risk_level": action.risk_level,
            "requires_confirmation": action.requires_confirmation,
            "outcome": outcome,
            "message": self._redact_text(message),
        }
        try:
            Config.AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(Config.AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            audio_log.log_error(f"Failed to write to audit log: {e}")

    def _timeline(self, stage, action, detail=""):
        emitter = getattr(self.controller, "_emit", None)
        if not callable(emitter):
            return
        payload = {
            "action": self._redact_sensitive_values(action.to_dict()),
            "detail": self._redact_text(detail),
        }
        emitter("timeline", stage, json.dumps(payload, ensure_ascii=False))

    def validate_action(self, action: Action):
        if not isinstance(action, Action):
            raise ValueError("Action must be an instance of Action dataclass")
        if not action.action_id or not isinstance(action.action_id, str):
            raise ValueError("action_id must be a non-empty string")
        if not action.skill or not isinstance(action.skill, str):
            raise ValueError("skill must be a non-empty string")
        if not action.operation or not isinstance(action.operation, str):
            raise ValueError("operation must be a non-empty string")
        if not isinstance(action.parameters, dict):
            raise ValueError("parameters must be a dictionary")
        if action.risk_level not in ["low", "medium", "high", "critical"]:
            raise ValueError("risk_level must be one of 'low', 'medium', 'high', 'critical'")
        if not isinstance(action.requires_confirmation, bool):
            raise ValueError("requires_confirmation must be a boolean")
        if not isinstance(action.reversible, bool):
            raise ValueError("reversible must be a boolean")
        # Optional fields can be None
        if action.permission_scope and not isinstance(action.permission_scope, str):
            raise ValueError("permission_scope must be a string or None")
        if action.permission_scope and action.permission_scope not in Config.PERMISSION_SCOPES:
            raise ValueError(f"Unknown permission scope: {action.permission_scope}")
        if action.rollback_action and not isinstance(action.rollback_action, str):
            raise ValueError("rollback_action must be a string or None")

    def assign_permission_scope(self, action: Action):
        """Assigns a permission scope to the action based on its skill, operation, or parameters."""

        allowed = self.TOOL_ALLOWLIST.get(action.skill, {})
        registered_scope = allowed.get(action.operation)
        if registered_scope:
            action.permission_scope = registered_scope
            return

        # If a scope is already explicitly set, validate it and use it.
        if action.permission_scope:
            if action.permission_scope not in Config.PERMISSION_SCOPES:
                audio_log.log_error(f"Unknown permission scope assigned to action {action.action_id}: {action.permission_scope}")
                # Fallback to a safe default if an invalid scope is explicitly set
                action.permission_scope = "SAFE_READ"
            return

        # Dynamic assignment based on keywords in operation and parameters
        op = action.operation.lower()
        params_str = json.dumps(action.parameters).lower()

        # Prioritize more specific, higher-risk operations first
        if "delete" in op or "remove" in op or "trash" in params_str:
            action.permission_scope = "FILE_DELETE"
        elif "send" in op and ("email" in op or "mail" in action.skill.lower()):
            action.permission_scope = "EMAIL_SEND"
        elif "submit" in op and "form" in op:
            action.permission_scope = "FORM_SUBMIT"
        elif "power" in op or "shutdown" in op or "restart" in op:
            action.permission_scope = "SYSTEM_POWER"
        elif "admin" in op or "elevated" in op or "install" in op:
            action.permission_scope = "ADMINISTRATOR"
        elif "security" in op or "permission" in op or "firewall" in op:
            action.permission_scope = "SECURITY_CHANGE"

        # General file operations (modify, write, read) - order is important
        elif "write" in op or "save" in op or "create" in op: # Check for write/create before general file modify
            action.permission_scope = "SAFE_WRITE"
        elif "modify" in op or "rename" in op or "move" in op or "edit" in op or "update" in op or ("file" in op and "read" not in op and "write" not in op and "create" not in op) or ("folder" in op and "read" not in op and "write" not in op and "create" not in op) or ("document" in op and "read" not in op and "write" not in op and "create" not in op):
            action.permission_scope = "FILE_MODIFY"
        elif "read" in op or "view" in op or "get" in op or "list" in op:
            action.permission_scope = "SAFE_READ"
            
        # Other actions
        elif "draft" in op and ("email" in op or "mail" in action.skill.lower()):
            action.permission_scope = "EMAIL_DRAFT"
        elif "navigate" in op or "browse" in op or "open_page" in op:
            action.permission_scope = "BROWSER_NAVIGATE"
        elif "open_app" in op or "control_desktop" in op or "window_action" in op:
            action.permission_scope = "DESKTOP_CONTROL"
        else:
            # Default to SAFE_READ if no specific scope is determined
            action.permission_scope = "SAFE_READ"

        if action.permission_scope not in Config.PERMISSION_SCOPES:
            audio_log.log_error(f"Assigned unknown permission scope {action.permission_scope} to action {action.action_id} - defaulting to SAFE_READ")
            action.permission_scope = "SAFE_READ"  # Ensure a valid scope

    def requires_confirmation(self, action: Action) -> bool:
        """Determines if an action requires explicit user confirmation based on rules and assigned scope."""
        if action.requires_confirmation: # Explicitly marked as requiring confirmation
            return True

        rules = Config.CONFIRMATION_RULES
        required = {str(operation).casefold()
                    for operation in rules.get("confirmation_required", set())}
        return action.operation.casefold() in required

    def action_from_intent(self, intent):
        if not isinstance(intent, dict):
            raise ValueError("Intent must be an object")
        if set(intent) - {"skill", "params"}:
            raise ValueError("Intent contains unsupported fields")
        full_skill = intent.get("skill")
        parameters = intent.get("params", {}) or {}
        if not isinstance(full_skill, str) or not full_skill.strip():
            raise ValueError("Intent skill must be a non-empty string")
        if not isinstance(parameters, dict):
            raise ValueError("Intent params must be an object")
        policy = self.INTENT_ALLOWLIST.get(full_skill)
        if policy is None:
            raise ValueError(f"Unregistered intent: {full_skill}")
        if "." in full_skill:
            skill, operation = full_skill.split(".", 1)
        else:
            skill, operation = full_skill, "respond"
        scope, risk = policy
        requires_confirmation = False
        if full_skill == "desktop.organize":
            requires_confirmation = True
        elif full_skill == "system.shutdown":
            requires_confirmation = parameters.get("action", "shutdown") != "cancel"
        elif full_skill == "app.close" and parameters.get("target") == "__all__":
            requires_confirmation = True
            operation = "close_everything"
            risk = "high"
            parameters = dict(parameters)
            parameters["target"] = "All resources opened by JARVIS"
        elif full_skill in ("email.send", "whatsapp.reply", "browser.submit_form", "browser.upload"):
            requires_confirmation = True
        elif full_skill == "browser.fill_form":
            sensitive = {"password", "token", "card", "bank", "passport", "identity", "ssn"}
            fields = parameters.get("fields", {}) or {}
            requires_confirmation = any(
                any(marker in str(key).lower() for marker in sensitive)
                for key in fields
            )
        return Action(
            action_id=uuid.uuid4().hex,
            skill=skill,
            operation=operation,
            parameters=dict(parameters),
            permission_scope=scope,
            risk_level=risk,
            requires_confirmation=requires_confirmation,
            reversible=scope not in {"EMAIL_SEND", "SYSTEM_POWER", "FILE_DELETE"},
            rollback_action=None,
        )

    @staticmethod
    def _decision_outcome(decision):
        if decision is True:
            return "approved_once"
        if decision is False or decision is None:
            return "denied"
        normalized = str(decision).strip().lower().replace(" ", "_")
        if normalized in {"approve", "approved", "approve_once", "yes", "true"}:
            return "approved_once"
        if normalized in {"cancel", "cancel_task", "cancelled", "canceled"}:
            return "cancelled"
        if normalized in {"timeout", "timed_out"}:
            return "timeout"
        return "denied"

    def _confirm(self, action):
        if not self.requires_confirmation(action):
            return "approved_once"
        self.audit_log(action, "confirmation_requested", "Waiting for user decision")
        self._timeline("confirmation_requested", action, "Waiting for user decision")
        self.controller.speak(f"Sir, I need confirmation to {action.operation}.")
        audio_log.log(
            f"[ActionManager] Requesting confirmation for action_id: "
            f"{action.action_id}, operation: {action.operation}"
        )
        try:
            controller_confirm = getattr(type(self.controller), "confirm", None)
            if callable(controller_confirm):
                decision = self.controller.confirm(action)
            else:
                decision = self.controller.agent.confirm(action)
        except Exception:
            decision = False
        outcome = self._decision_outcome(decision)
        self.audit_log(action, outcome, "Confirmation decision received")
        self._timeline("confirmation_result", action, outcome)
        return outcome

    def execute_intent(self, intent, executor):
        action = self.action_from_intent(intent)
        self.validate_action(action)
        self.audit_log(action, "requested", "Registered intent received")
        self._timeline("validated", action, "Allowlist validation passed")
        outcome = self._confirm(action)
        if outcome != "approved_once":
            if outcome == "cancelled":
                self.controller.stop_task()
                self.controller.speak("Task cancelled, sir.")
                return "Task cancelled by user."
            if outcome == "timeout":
                self.controller.speak("Confirmation timed out, sir.")
                return "Action denied because confirmation timed out."
            self.controller.speak("Action denied, sir.")
            return "Action denied by user."
        try:
            set_state = getattr(self.controller, "_set_state", None)
            if callable(set_state):
                set_state("executing", f"{action.skill}.{action.operation}")
            self._timeline("executing", action, "Registered executor started")
            result = executor()
        except Exception:
            self.audit_log(action, "failed", "Registered action failed")
            self._timeline("failed", action, "Registered executor failed")
            raise
        self.audit_log(action, "success", "Registered action completed")
        self._timeline("completed", action, "Registered executor completed")
        return result

    def execute_action(self, action: Action):
        self.assign_permission_scope(action)
        self.validate_action(action)

        operations = self.TOOL_ALLOWLIST.get(action.skill)
        if operations is None:
            self.audit_log(action, "rejected", "Unknown skill")
            raise ValueError(f"Unknown skill: {action.skill}")
        if action.operation not in operations:
            self.audit_log(action, "rejected", "Unknown operation")
            raise ValueError(f"Unknown operation: {action.skill}.{action.operation}")

        outcome = self._confirm(action)
        if outcome != "approved_once":
            if outcome == "cancelled":
                self.controller.stop_task()
                return "Task cancelled by user."
            if outcome == "timeout":
                return "Action denied because confirmation timed out."
            self.controller.speak("Action denied, sir.")
            return "Action denied by user."

        audio_log.log(f"[ActionManager] Executing action: {action.skill}.{action.operation} with params {self._redact_sensitive_values(action.parameters)}")
        result = self._execute_registered(action)
        self.audit_log(action, "success", "Registered action completed")
        return result

    def _execute_registered(self, action):
        params = dict(action.parameters)
        if action.skill == "windows":
            from core.windows_controller import WindowsController
            windows = getattr(self.controller, "windows_controller", None)
            if windows is None:
                windows = WindowsController(self.controller.ctx)
                self.controller.windows_controller = windows
            operation = {
                "open_application": windows.open_application,
                "open_folder": windows.open_folder,
                "open_file": windows.open_file,
                "open_uri": windows.open_uri,
                "focus_window": windows.focus_window,
                "minimize_window": windows.minimize_window,
                "maximize_window": windows.maximize_window,
                "restore_window": windows.restore_window,
                "move_window": windows.move_window,
                "resize_window": windows.resize_window,
                "close_window": windows.close_window,
                "close_application": windows.close_application,
                "close_resource": windows.close_resource,
                "close_recent_jarvis_item": windows.close_recent_jarvis_item,
                "close_all_jarvis_items": windows.close_all_jarvis_items,
            }[action.operation]
            return str(operation(**params))
        if action.skill == "office_word":
            from skills import word_skill
            operation = {
                "create_document": lambda **_: word_skill.create_document(self.controller.ctx),
                "create_research_document": lambda topic, report_length="full", **_: word_skill.create_live_document(
                    topic, self.controller.ctx, report_length=report_length
                ),
                "insert_text": lambda text, **_: word_skill.insert_text(text, self.controller.ctx),
                "save_document": lambda path, **_: word_skill.save_document(path, self.controller.ctx),
            }[action.operation]
            return str(operation(**params))
        if action.skill == "browser":
            if action.operation != "close":
                return self.controller.ctx.web_automation.execute({
                    "skill": f"browser.{action.operation}", "params": params,
                })
            browser = self.controller.ctx.browser
            operation = {
                "close": lambda: browser.close_browser(),
            }[action.operation]
            return str(operation(**params))
        if action.skill == "office":
            return self.controller.ctx.desktop_automation.execute({
                "skill": f"office.{action.operation}", "params": params,
            })
        if action.skill == "website":
            return self.controller.ctx.website_automation.execute({
                "skill": f"website.{action.operation}", "params": params,
            })
        if action.skill == "research":
            from skills import research
            operation = {
                "search_web": research.search_web,
                "read_source": research.read_source,
                "summarize_sources": research.summarize_sources,
            }[action.operation]
            return operation(**params)
        if action.skill == "task":
            task = self.controller.ctx.live_task
            operation = {
                "pause": task.pause,
                "resume": task.resume,
                "cancel": task.cancel,
                "speed": task.set_speed,
            }[action.operation]
            return str(operation(**params))
        if action.skill == "system":
            from skills import system_control
            if action.operation == "emergency_stop":
                self.controller.stop_task()
                self.controller.ctx.web_automation.emergency_stop()
                self.controller.ctx.live_task.cancel()
                return "Emergency stop completed."
            if action.operation == "status":
                return system_control.status_report()
            return system_control.shutdown(params.get("action", "shutdown"), self.controller.ctx)
        raise ValueError(f"No executor for {action.skill}.{action.operation}")
