"""Constrained Hermes connection adapter.

The official audit does not identify a stable structured-planning HTTP API.
Accordingly JARVIS uses the official quiet one-shot CLI for diagnostics and
JSON planning; it never grants Hermes tools or executes returned actions.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from config import Config
from .hermes_protocol import parse_plan_json


class HermesAdapterError(RuntimeError): pass


_SESSION_ID = re.compile(r"\b\d{8}_\d{6}_[0-9a-f]{6,}\b", re.I)


def _session_failure_detail(output: str) -> str:
    """Return only safe provider metadata from one exact Hermes session dump."""
    match = _SESSION_ID.search(str(output or ""))
    if not match:
        return ""
    session_id = match.group(0)
    sessions = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "sessions"
    try:
        dumps = sorted(
            sessions.glob(f"request_dump_{session_id}_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        payload = json.loads(dumps[0].read_text(encoding="utf-8"))
        error = payload.get("error") if isinstance(payload, dict) else None
        error = error if isinstance(error, dict) else {}
        body = error.get("body") if isinstance(error.get("body"), dict) else {}
        metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        code = error.get("status_code") or error.get("code") or body.get("code")
        message = metadata.get("raw") or body.get("message") or "Provider request failed"
        provider = str(metadata.get("provider_name") or "").strip()
        safe = re.sub(
            r"(?i)(?:api[_ -]?key|authorization|bearer|user_id)\s*[:=]\s*\S+",
            "[REDACTED]", str(message),
        ).strip()[:360]
        prefix = f"Hermes provider error {code}" if code else "Hermes provider error"
        suffix = f" (upstream: {provider[:80]})" if provider else ""
        return f"{prefix}: {safe}{suffix}"
    except (OSError, ValueError, IndexError, TypeError):
        return ""


def _background_process_kwargs():
    """Hermes diagnostics are captured; they must never create a console."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return {"creationflags": flags} if flags else {}


class HermesAdapter:
    def __init__(self, enabled=None, mode=None, executable=None, timeout=None):
        self.enabled = Config.HERMES_ENABLED if enabled is None else bool(enabled)
        self.mode = (Config.HERMES_MODE if mode is None else mode).lower().strip()
        self.executable = (Config.HERMES_EXECUTABLE if executable is None else executable).strip()
        self.timeout = Config.HERMES_TIMEOUT_SECONDS if timeout is None else int(timeout)
        self.provider = Config.HERMES_PROVIDER.strip()
        self.model = (Config.HERMES_MODEL or Config.OPENROUTER_MODEL).strip()
        self._cancel_event = threading.Event()
        self._process_lock = threading.RLock()
        self._process = None

    def configure(self, *, enabled, mode, provider, model, timeout=None) -> None:
        """Apply non-secret GUI settings to this live adapter instance."""
        normalized_mode = str(mode or "disabled").strip().lower()
        if normalized_mode not in {"cli", "disabled"}:
            raise HermesAdapterError("unsupported Hermes runtime mode")
        self.mode = normalized_mode
        self.enabled = bool(enabled) and normalized_mode == "cli"
        self.provider = str(provider or "").strip()
        self.model = str(model or "").strip()
        if timeout is not None:
            self.timeout = max(1, int(timeout))

    @property
    def running(self) -> bool:
        with self._process_lock:
            return self._process is not None and self._process.poll() is None

    @staticmethod
    def _terminate_owned_process(process) -> None:
        """Stop only the process JARVIS launched, plus its exact descendants."""
        descendants = []
        try:
            import psutil
            root = psutil.Process(process.pid)
            launched_at = getattr(process, "_jarvis_create_time", None)
            if launched_at is not None and abs(root.create_time() - launched_at) < 0.001:
                descendants = root.children(recursive=True)
        except Exception:
            descendants = []
        for child in reversed(descendants):
            try:
                child.terminate()
            except Exception:
                pass
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        for child in reversed(descendants):
            try:
                if child.is_running():
                    child.kill()
            except Exception:
                pass

    def cancel(self) -> bool:
        """Cancel the current adapter-owned request without matching by name."""
        self._cancel_event.set()
        with self._process_lock:
            process = self._process
        if process is None or process.poll() is not None:
            return False
        self._terminate_owned_process(process)
        return True

    def _run_cancellable(self, command, *, cwd=None):
        self._cancel_event.clear()
        try:
            with self._process_lock:
                process = subprocess.Popen(
                    command, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace", cwd=cwd,
                    **_background_process_kwargs(),
                )
                try:
                    import psutil
                    process._jarvis_create_time = psutil.Process(process.pid).create_time()
                except Exception:
                    process._jarvis_create_time = None
                self._process = process
            deadline = time.monotonic() + max(1, self.timeout)
            while True:
                if self._cancel_event.is_set():
                    self._terminate_owned_process(process)
                    raise HermesAdapterError("Hermes request cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate_owned_process(process)
                    raise HermesAdapterError("Hermes planning timed out")
                try:
                    stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if self._cancel_event.is_set():
                raise HermesAdapterError("Hermes request cancelled")
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except HermesAdapterError:
            raise
        except OSError as exc:
            raise HermesAdapterError(f"Hermes planning failed: {exc}") from exc
        finally:
            with self._process_lock:
                if self._process is locals().get("process"):
                    self._process = None

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
        if not self.model or not self.provider:
            raise HermesAdapterError("Hermes provider or model is not configured")
        return [
            str(python), str(launcher), "chat", "--quiet", "--safe-mode",
            "--provider", self.provider, "--model", self.model,
            "--toolsets", "context_engine", "--max-turns", "1",
            "--source", "tool", "--query", prompt,
        ]

    def diagnostic(self, command="--help") -> str:
        if not self.enabled or self.mode == "disabled":
            raise HermesAdapterError("Hermes is disabled")
        if self.mode != "cli":
            raise HermesAdapterError("only audited CLI diagnostics are supported")
        if command not in {"--help", "doctor"}:
            raise HermesAdapterError("unsupported Hermes diagnostic")
        try:
            result = subprocess.run([self._binary(), command], shell=False, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace",
                                    timeout=self.timeout, check=False,
                                    **_background_process_kwargs())
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
        result = self._run_cancellable(self._pilot_command(prompt), cwd=str(Config.TEMP_DIR))
        if result.returncode:
            raw_detail = (result.stderr or result.stdout or "Hermes plan request failed").strip()
            detail = _session_failure_detail(raw_detail) or raw_detail
            raise HermesAdapterError(detail[:500])
        return parse_plan_json(result.stdout)
