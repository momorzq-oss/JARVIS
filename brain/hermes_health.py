"""Truthful Hermes status with no network or process side effects by default."""
from __future__ import annotations

from .hermes_adapter import HermesAdapter, HermesAdapterError
from .hermes_runtime_manager import HermesRuntimeManager


def hermes_health(adapter=None, *, probe=False) -> dict:
    """Return cached/configuration health unless an explicit probe is asked for.

    The routine status path is latency-sensitive and may run from the GUI
    thread.  Merely rendering mission control must never launch Hermes.
    """
    adapter = adapter or HermesAdapter()
    runtime = HermesRuntimeManager()
    if not adapter.enabled or adapter.mode == "disabled":
        installed = runtime.installed
        detail = "HERMES_ENABLED=false"
        if installed:
            detail += f"; external runtime installed at {runtime.repo}"
        return {
            "status": "disabled", "detail": detail,
            "installed": installed,
            "repository": str(runtime.repo) if installed else "",
            "gateway": "OFFLINE",
        }
    if not probe:
        installed = runtime.installed
        return {
            "status": "configured" if installed else "unavailable",
            "detail": (
                "External Hermes runtime configured; explicit health probe pending"
                if installed else "Hermes is enabled but its external runtime was not found"
            ),
            "installed": installed,
            "repository": str(runtime.repo) if installed else "",
            "gateway": "OFFLINE",
        }
    try:
        adapter.diagnostic("--help")
    except HermesAdapterError as exc:
        return {"status": "unavailable", "detail": str(exc), "installed": False}
    return {"status": "diagnostic_only", "detail": "CLI found; planning remains blocked", "installed": True}
