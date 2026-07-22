"""Choose the user-invisible engine while preserving native JARVIS preference."""
from __future__ import annotations


class UnifiedToolRouter:
    def choose(self, request: str):
        text = str(request).lower()
        if "research" in text and any(word in text for word in ("word", "report", "document")):
            return "HYBRID"
        if any(word in text for word in ("word", "excel", "powerpoint", "open downloads", "focus window")):
            return "JARVIS"
        if any(word in text for word in ("background", "schedule", "build", "debug", "repository", "code")):
            return "HERMES"
        return "JARVIS"
