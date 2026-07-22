"""Minimal, non-executing Hermes connection adapter.

The official audit does not identify a stable structured-planning HTTP API.
Accordingly JARVIS supports disabled mode and narrowly scoped CLI diagnostics
only; it never feeds an unrestricted prompt into Hermes or grants tools.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from config import Config
from .hermes_protocol import parse_plan_json


class HermesAdapterError(RuntimeError): pass


class HermesAdapter:
    def __init__(self, enabled=None, mode=None, executable=None, timeout=None):
        self.enabled = Config.HERMES_ENABLED if enabled is None else bool(enabled)
        self.mode = (Config.HERMES_MODE if mode is None else mode).lower().strip()
        self.executable = (Config.HERMES_EXECUTABLE if executable is None else executable).strip()
        self.timeout = Config.HERMES_TIMEOUT_SECONDS if timeout is None else int(timeout)

    def _binary(self) -> str:
        candidate = self.executable or shutil.which("hermes")
        if not candidate:
            raise HermesAdapterError("Hermes is not installed")
        path = Path(candidate)
        if self.executable and not path.is_file():
            raise HermesAdapterError("configured Hermes executable was not found")
        return str(path if path.exists() else candidate)

    def _pilot_command(self, prompt: str) -> list[str]:
        """Official CLI one-shot with the documented empty `context_engine` toolset."""
        root = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes-agent"
        python = Path(self.executable) if self.executable else root / "venv" / "Scripts" / "python.exe"
        launcher = root / "hermes"
        if not python.is_file() or not launcher.is_file():
            raise HermesAdapterError("Hermes pilot runtime is not installed")
        model = Config.HERMES_MODEL or Config.OPENROUTER_MODEL
        if not model or not Config.HERMES_PROVIDER:
            raise HermesAdapterError("Hermes provider or model is not configured")
        return [str(python), str(launcher), "--safe-mode", "--provider", Config.HERMES_PROVIDER,
                "--model", model, "--toolsets", "context_engine", "-z", prompt]

    def diagnostic(self, command="--help") -> str:
        if not self.enabled or self.mode == "disabled":
            raise HermesAdapterError("Hermes is disabled")
        if self.mode != "cli":
            raise HermesAdapterError("only audited CLI diagnostics are supported")
        if command not in {"--help", "doctor"}:
            raise HermesAdapterError("unsupported Hermes diagnostic")
        try:
            result = subprocess.run([self._binary(), command], shell=False, capture_output=True,
                                    text=True, timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HermesAdapterError(f"Hermes diagnostic failed: {exc}") from exc
        if result.returncode:
            raise HermesAdapterError((result.stderr or result.stdout or "Hermes failed").strip()[:500])
        return (result.stdout or result.stderr).strip()[:4000]

    def plan(self, request):
        """Ask Hermes for text-only JSON, then validate it before JARVIS sees it."""
        if not self.enabled or self.mode != "cli":
            raise HermesAdapterError("Hermes planning is disabled")
        if Config.HERMES_TOOL_ACCESS_MODE != "jarvis_registry_only":
            raise HermesAdapterError("Hermes tool access mode is not safe")
        prompt = (
            "Return ONLY the JARVIS protocol 1.0 JSON plan. Do not call tools, write code, "
            "use shell commands, access files, browse, schedule work, save memory, or delegate. "
            "Use only capability ids in this supplied request.\nREQUEST:\n" +
            json.dumps(request.to_dict(), ensure_ascii=True)
        )
        try:
            result = subprocess.run(self._pilot_command(prompt), shell=False, capture_output=True,
                                    text=True, timeout=self.timeout, check=False,
                                    cwd=str(Config.TEMP_DIR))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HermesAdapterError(f"Hermes planning failed: {exc}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "Hermes plan request failed").strip()
            raise HermesAdapterError(detail[:500])
        return parse_plan_json(result.stdout)
