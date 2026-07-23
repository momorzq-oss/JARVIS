"""Dynamic registry built from real skill modules and approved operations."""
import dataclasses
import importlib
import inspect
import pkgutil
import threading
import time
from pathlib import Path

from core.action_manager import ActionManager
from core.capability_health import CapabilityHealth, DEGRADED


@dataclasses.dataclass
class CapabilityRecord:
    capability_id: str
    skill: str
    operation: str
    status: str
    permission: str = "UNASSIGNED"
    risk: str = "unknown"
    connected: bool = False
    description: str = ""
    dependencies: tuple[str, ...] = ()
    detail: str = ""
    last_checked: float = 0.0
    last_success: float | None = None
    last_failure: float | None = None
    voice_examples: tuple[str, ...] = ()
    gui_examples: tuple[str, ...] = ()


class CapabilityRegistry:
    MODULE_DEFAULT_SCOPES = {
        "browser": "BROWSER_NAVIGATE",
        "chat": "SAFE_READ",
        "coder": "SAFE_WRITE",
        "emailer": "SAFE_READ",
        "excel_skill": "OFFICE_EDIT",
        "media": "DESKTOP_CONTROL",
        "news": "SAFE_READ",
        "office_close": "DESKTOP_CONTROL",
        "office_service": "OFFICE_EDIT",
        "organizer": "FILE_MODIFY",
        "ppt_skill": "OFFICE_EDIT",
        "research": "BROWSER_NAVIGATE",
        "university_assignment": "OFFICE_EDIT",
        "system_control": "DESKTOP_CONTROL",
        "whatsapp": "FORM_SUBMIT",
        "window_control": "DESKTOP_CONTROL",
        "word_skill": "OFFICE_EDIT",
    }

    INTENT_MODULES = {
        "app": "system_control",
        "window": "window_control",
        "system": "system_control",
        "task": None,
        "media": "media",
        "browser": "browser",
        "web": "browser",
        "news": "news",
        "email": "emailer",
        "whatsapp": "whatsapp",
        "office_word": "word_skill",
        "word": "word_skill",
        "excel": "excel_skill",
        "ppt": "ppt_skill",
        "desktop": "organizer",
        "codex": "coder",
        "research": "research",
        "university": "university_assignment",
        "chat": "chat",
        "smalltalk": "chat",
    }

    def __init__(self, controller=None):
        self.controller = controller
        self._lock = threading.RLock()
        self._records = {}
        self._scan_error = ""
        self._scanning = False

    @property
    def scanning(self):
        return self._scanning

    def discover(self):
        with self._lock:
            self._scanning = True
        records = {}
        try:
            import skills
            modules = sorted(
                module.name for module in pkgutil.iter_modules(skills.__path__)
                if not module.name.startswith("_")
            )
            for skill in modules:
                module_name = f"skills.{skill}"
                try:
                    module = importlib.import_module(module_name)
                    functions = {
                        name: value for name, value in inspect.getmembers(module, inspect.isfunction)
                        if not name.startswith("_") and value.__module__ == module_name
                    }
                    if "handle" in functions:
                        record = self._record_for_function(skill, "handle", functions["handle"])
                        records[record.capability_id] = record
                    for name, function in functions.items():
                        if name == "handle":
                            continue
                        record = self._record_for_function(skill, name, function)
                        records[record.capability_id] = record
                except Exception as exc:
                    capability_id = f"{skill}.__module__"
                    records[capability_id] = CapabilityRecord(
                        capability_id, skill, "__module__", "BROKEN",
                        detail=str(exc), last_checked=time.time(), last_failure=time.time(),
                    )

            self._add_approved_operations(records)
            with self._lock:
                self._records = records
                self._scan_error = ""
            return self.snapshot()
        except Exception as exc:
            with self._lock:
                self._scan_error = str(exc)
            return []
        finally:
            with self._lock:
                self._scanning = False

    def run_health_checks(self):
        if not self.snapshot():
            self.discover()
        health = CapabilityHealth(self.controller)
        now = time.time()
        with self._lock:
            for record in self._records.values():
                try:
                    health_skill = self.INTENT_MODULES.get(record.skill, record.skill)
                    health_skill = health_skill or record.skill
                    result = health.check(
                        health_skill,
                        callable_present=record.status != "MISSING",
                        import_error=record.detail if record.status == "BROKEN" else "",
                        operation=record.operation,
                    )
                    record.status = result.status
                    record.detail = result.detail
                    record.dependencies = result.dependencies
                    record.connected = result.status in ("WORKING", "CONNECTED")
                    record.last_checked = now
                    if record.connected:
                        record.last_success = now
                    elif result.status in ("BROKEN", "MISSING", DEGRADED):
                        record.last_failure = now
                except Exception as exc:
                    record.status = DEGRADED
                    record.detail = str(exc)
                    record.connected = False
                    record.last_checked = now
                    record.last_failure = now
        return self.snapshot()

    def snapshot(self):
        with self._lock:
            return [dataclasses.replace(record) for record in self._records.values()]

    def report(self):
        records = self.snapshot()
        counts = {}
        for record in records:
            counts[record.status] = counts.get(record.status, 0) + 1
        return {
            "total": len(records),
            "counts": counts,
            "scanning": self.scanning,
            "error": self._scan_error,
            "system": CapabilityHealth(self.controller).system_metrics(),
            "capabilities": [dataclasses.asdict(record) for record in records],
        }

    def skills_text(self):
        records = self.snapshot() or self.discover()
        grouped = {}
        for record in records:
            grouped.setdefault(record.skill, []).append(record)
        lines = []
        for skill in sorted(grouped):
            working = sum(record.connected for record in grouped[skill])
            lines.append(f"{skill}: {working}/{len(grouped[skill])} connected")
        return "\n".join(lines) if lines else "No capabilities discovered."

    def capabilities_text(self):
        records = self.snapshot() or self.discover()
        lines = []
        for record in sorted(records, key=lambda item: item.capability_id):
            detail = f" - {record.detail}" if record.detail else ""
            lines.append(f"{record.capability_id}: {record.status} [{record.permission}]{detail}")
        return "\n".join(lines) if lines else "No capabilities discovered."

    def _record_for_function(self, skill, operation, function):
        result = CapabilityHealth(self.controller).check(
            skill, callable_present=True, operation=operation
        )
        description = (inspect.getdoc(function) or "").splitlines()[0] if inspect.getdoc(function) else ""
        capability_id = f"{skill}.{operation}"
        permission = self._permission_for_function(skill, operation)
        return CapabilityRecord(
            capability_id, skill, operation, result.status,
            permission=permission, risk=self._risk_for_permission(permission),
            connected=result.status == "WORKING", description=description,
            dependencies=result.dependencies, detail=result.detail,
            last_checked=time.time(),
        )

    def _add_approved_operations(self, records):
        module_map = {"office_word": "word_skill"}
        for skill, operations in ActionManager.TOOL_ALLOWLIST.items():
            module_skill = module_map.get(skill, skill)
            for operation, permission in operations.items():
                capability_id = f"{skill}.{operation}"
                if capability_id in records:
                    records[capability_id].permission = permission
                    continue
                implemented = self._approved_operation_exists(skill, module_skill, operation)
                result = CapabilityHealth(self.controller).check(
                    module_skill, callable_present=implemented
                )
                records[capability_id] = CapabilityRecord(
                    capability_id, skill, operation, result.status,
                    permission=permission, risk=self._risk_for_permission(permission),
                    connected=result.status == "WORKING",
                    dependencies=result.dependencies, detail=result.detail,
                    last_checked=time.time(),
                )
        for full_skill, (permission, risk) in ActionManager.INTENT_ALLOWLIST.items():
            if "." in full_skill:
                intent_skill, operation = full_skill.split(".", 1)
            else:
                intent_skill, operation = full_skill, "respond"
            if full_skill in records:
                records[full_skill].permission = permission
                records[full_skill].risk = risk
                continue
            module_skill = self.INTENT_MODULES.get(intent_skill)
            implemented = self._intent_operation_exists(module_skill)
            health_skill = module_skill or intent_skill
            result = CapabilityHealth(self.controller).check(
                health_skill, callable_present=implemented, operation=operation
            )
            records[full_skill] = CapabilityRecord(
                full_skill, intent_skill, operation, result.status,
                permission=permission, risk=risk,
                connected=result.status == "WORKING",
                dependencies=result.dependencies, detail=result.detail,
                last_checked=time.time(),
            )

    def _permission_for_function(self, skill, operation):
        aliases = {
            ("word_skill", "create_document"): "office_word.create_document",
            ("word_skill", "create_live_document"): "office_word.create_research_document",
        }
        full_skill = aliases.get((skill, operation), f"{skill}.{operation}")
        policy = ActionManager.INTENT_ALLOWLIST.get(full_skill)
        if policy:
            return policy[0]
        return self.MODULE_DEFAULT_SCOPES.get(skill, "SAFE_READ")

    @staticmethod
    def _risk_for_permission(permission):
        if permission in {"SYSTEM_POWER", "ADMINISTRATOR", "SECURITY_CHANGE"}:
            return "critical"
        if permission in {"FILE_DELETE", "EMAIL_SEND", "FORM_SUBMIT"}:
            return "high"
        if permission in {"FILE_MODIFY", "OFFICE_EDIT", "SAFE_WRITE"}:
            return "medium"
        return "low"

    @staticmethod
    def _intent_operation_exists(module_skill):
        if module_skill is None:
            return True
        try:
            module = importlib.import_module(f"skills.{module_skill}")
            if module_skill == "browser":
                return callable(getattr(module, "BrowserEngine", None))
            return callable(getattr(module, "handle", None))
        except Exception:
            return False

    @staticmethod
    def _approved_operation_exists(skill, module_skill, operation):
        # These capability namespaces are implemented by the trusted adapter
        # services attached to AssistantContext, not by a same-named module in
        # ``skills``.  Treating them as imports made valid Office and website
        # operations appear as fake "MISSING" capabilities.
        if skill in ("windows", "task", "browser", "system", "office", "website"):
            return True
        try:
            module = importlib.import_module(f"skills.{module_skill}")
            translated = {
                "create_research_document": "create_live_document",
            }.get(operation, operation)
            return callable(getattr(module, translated, None))
        except Exception:
            return False
