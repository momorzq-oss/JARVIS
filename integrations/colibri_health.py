"""Non-invasive Colibri health reporting."""
from __future__ import annotations

from .colibri_adapter import ColibriAdapter, ColibriError


def colibri_health(adapter=None) -> dict:
    """Return a safe status snapshot without launching or installing Colibri."""
    adapter = adapter or ColibriAdapter()
    if not adapter.enabled:
        return {"status": "disabled", "detail": "COLIBRI_ENABLED=false"}
    if adapter.mode != "http_api":
        return {"status": "misconfigured", "detail": "COLIBRI_MODE must be http_api"}
    try:
        payload = adapter.health()
    except ColibriError as exc:
        return {"status": "unavailable", "detail": str(exc)}
    return {"status": "ready", "detail": "local Colibri API reachable", "payload": payload}
