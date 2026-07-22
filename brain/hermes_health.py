"""Truthful Hermes status with no network or process side effects by default."""
from __future__ import annotations

from .hermes_adapter import HermesAdapter, HermesAdapterError


def hermes_health(adapter=None) -> dict:
    adapter = adapter or HermesAdapter()
    if not adapter.enabled or adapter.mode == "disabled":
        return {"status": "disabled", "detail": "HERMES_ENABLED=false", "installed": False}
    try:
        adapter.diagnostic("--help")
    except HermesAdapterError as exc:
        return {"status": "unavailable", "detail": str(exc), "installed": False}
    return {"status": "diagnostic_only", "detail": "CLI found; planning remains blocked", "installed": True}
