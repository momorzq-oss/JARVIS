"""Manage the externally installed Hermes runtime as a JARVIS subsystem."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _background_process_kwargs():
    """Runtime probes are hidden, captured maintenance commands."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return {"creationflags": flags} if flags else {}


class HermesRuntimeManager:
    """Discovery and read-only probes; JARVIS owns the user experience."""
    def __init__(self, home=None, timeout=20):
        self.home = Path(home or os.environ.get("HERMES_HOME") or Path(os.environ.get("LOCALAPPDATA", "")) / "hermes")
        self.repo = self.home / "hermes-agent"
        self.python = self.repo / "venv" / "Scripts" / "python.exe"
        self.launcher = self.repo / "hermes"
        self.timeout = timeout
        self.last_error = ""

    @property
    def installed(self):
        return self.python.is_file() and self.launcher.is_file()

    def _run(self, args, timeout=None):
        if not self.installed:
            raise RuntimeError("Hermes is not installed")
        return subprocess.run([str(self.python), str(self.launcher), *args], shell=False,
            cwd=str(self.repo), text=True, capture_output=True, timeout=timeout or self.timeout,
            **_background_process_kwargs(),
            check=False)

    def snapshot(self):
        if not self.installed:
            return {"state": "NOT_INSTALLED", "detail": "External Hermes runtime not found", "installed": False}
        try:
            result = self._run(["--version"])
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout).strip())
            return {"state": "READY", "detail": result.stdout.strip(), "installed": True,
                    "home": str(self.home), "repository": str(self.repo), "gateway": "OFFLINE"}
        except Exception as exc:
            self.last_error = str(exc)
            return {"state": "DEGRADED", "detail": self.last_error, "installed": True}

    def discover_tools(self):
        """Read official runtime metadata without launching an agent or tools."""
        code = (
            "import json; from toolsets import TOOLSETS; "
            "print(json.dumps({k:{'description':v.get('description',''),'tools':v.get('tools',[]),"
            "'includes':v.get('includes',[])} for k,v in TOOLSETS.items()}))"
        )
        if not self.installed:
            return []
        try:
            result = subprocess.run([str(self.python), "-c", code], shell=False, cwd=str(self.repo),
                text=True, capture_output=True, timeout=self.timeout,
                **_background_process_kwargs(), check=False)
            if result.returncode:
                raise RuntimeError(result.stderr.strip())
            data = json.loads(result.stdout)
            records = {}
            for group, spec in data.items():
                for tool in spec.get("tools", []):
                    identifier = f"hermes.{tool}"
                    item = records.setdefault(identifier, {"id": identifier, "engine": "HERMES",
                        "toolsets": [], "operation": tool, "description": spec.get("description", ""),
                        "status": "REQUIRES_CONFIGURATION", "risk": self._risk(tool)})
                    item["toolsets"].append(group)
            return list(records.values())
        except Exception as exc:
            self.last_error = str(exc)
            return []

    @staticmethod
    def _risk(tool):
        low = {"todo", "clarify", "session_search"}
        high = {"terminal", "process", "execute_code", "write_file", "patch", "cronjob", "send_message", "computer_use"}
        return "high" if tool in high else "low" if tool in low else "medium"
