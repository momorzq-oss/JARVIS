"""Non-destructive health checks for discovered JARVIS capabilities."""
import ctypes
import importlib.util
import shutil
import threading
from dataclasses import dataclass

from config import Config


WORKING = "WORKING"
CONNECTED = "CONNECTED"
DISABLED = "DISABLED"
REQUIRES_CONFIGURATION = "REQUIRES_CONFIGURATION"
REQUIRES_LOGIN = "REQUIRES_LOGIN"
BROKEN = "BROKEN"
MISSING = "MISSING"
DEGRADED = "DEGRADED"


@dataclass(frozen=True)
class HealthResult:
    status: str
    detail: str = ""
    dependencies: tuple[str, ...] = ()


CONFIG_REQUIREMENTS = {
    "chat": ("OPENROUTER_API_KEY",),
    "coder": ("OPENROUTER_API_KEY",),
    "research": ("OPENROUTER_API_KEY",),
}

OPERATION_CONFIG_REQUIREMENTS = {
    ("word_skill", "create_live_document"): ("OPENROUTER_API_KEY",),
    ("word_skill", "write_document"): ("OPENROUTER_API_KEY",),
    ("word_skill", "continue_document"): ("OPENROUTER_API_KEY",),
}

LOGIN_REQUIREMENTS = {
    "emailer": "Google account login or SMTP configuration required",
    "gmail": "Google account login required",
    "whatsapp": "WhatsApp Desktop login required",
}

LOGIN_ACCOUNTS = {
    "emailer": "gmail",
    "gmail": "gmail",
    "whatsapp": "whatsapp",
}

OPTIONAL_DEPENDENCIES = {
    "browser": ("playwright",),
    "excel_skill": ("win32com",),
    "office_service": ("win32com",),
    "ppt_skill": ("win32com",),
    "word_skill": ("docx", "win32com"),
    "window_control": ("pygetwindow",),
}


class CapabilityHealth:
    def __init__(self, controller=None):
        self.controller = controller

    @staticmethod
    def _configured(name):
        value = str(getattr(Config, name, "") or "").strip()
        if not value:
            return False
        lowered = value.lower()
        if any(marker in lowered for marker in (
            "your_", "your-", "replace", "placeholder", "changeme",
            "example_key", "example-password", "api-key-here",
        )):
            return False
        if name == "OPENROUTER_API_KEY" and not value.startswith("sk-or-v1-"):
            return False
        if name == "EMAIL_ADDRESS" and "@" not in value:
            return False
        return True

    def check(self, skill, callable_present=True, import_error="", operation=None):
        if import_error:
            return HealthResult(BROKEN, import_error)
        if not callable_present:
            return HealthResult(MISSING, "Approved operation is not implemented")

        requirements = OPERATION_CONFIG_REQUIREMENTS.get(
            (skill, operation), CONFIG_REQUIREMENTS.get(skill, ())
        )
        missing_config = [name for name in requirements if not self._configured(name)]
        if missing_config:
            return HealthResult(
                REQUIRES_CONFIGURATION,
                "Missing " + ", ".join(missing_config),
                tuple(missing_config),
            )

        login_detail = LOGIN_REQUIREMENTS.get(skill)
        if login_detail:
            account = LOGIN_ACCOUNTS.get(skill)
            if account:
                try:
                    from core.account_connections import AccountConnectionManager
                    connection = AccountConnectionManager.status(account)
                    if connection["connected"]:
                        return HealthResult(
                            WORKING,
                            f"{account.title()} connection verified: {connection['detail']}",
                        )
                except Exception:
                    pass
            return HealthResult(REQUIRES_LOGIN, login_detail)

        dependencies = OPTIONAL_DEPENDENCIES.get(skill, ())
        missing_dependencies = [name for name in dependencies
                                if importlib.util.find_spec(name) is None]
        if missing_dependencies:
            return HealthResult(
                DEGRADED,
                "Optional dependency unavailable: " + ", ".join(missing_dependencies),
                tuple(missing_dependencies),
            )

        return HealthResult(WORKING, "Implementation available", tuple(dependencies))

    def system_metrics(self):
        """Collect bounded local metrics without process-enumeration APIs.

        Importing psutil on Windows immediately performs per-CPU native
        queries.  Those calls can block indefinitely on a damaged performance
        counter provider while holding Python execution, which used to freeze
        JARVIS during every mission-control refresh.  Memory and disk values
        below come from constant-time OS/stdlib calls; unavailable values are
        reported honestly instead of risking the GUI.
        """
        try:
            ram_percent = None
            if hasattr(ctypes, "windll"):
                class MemoryStatus(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                memory = MemoryStatus()
                memory.dwLength = ctypes.sizeof(MemoryStatus)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
                    ram_percent = float(memory.dwMemoryLoad)

            disk = shutil.disk_usage(str(Config.BASE_DIR.anchor or "C:\\"))
            disk_percent = (
                round((disk.used / disk.total) * 100.0, 1) if disk.total else None
            )
            return {
                "cpu_percent": None,
                "ram_percent": ram_percent,
                "disk_percent": disk_percent,
                "network_sent_bytes": None,
                "network_received_bytes": None,
                "temperature_c": None,
                "python_threads": threading.active_count(),
                "gpu_percent": None,
                "vram_percent": None,
                "status": WORKING,
            }
        except Exception as exc:
            return {"status": DEGRADED, "detail": str(exc)}
