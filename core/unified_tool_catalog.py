"""One namespaced catalog for JARVIS-native and official Hermes tools."""
from __future__ import annotations

import threading

from brain.hermes_runtime_manager import HermesRuntimeManager
from config import Config


class UnifiedToolCatalog:
    def __init__(self, registry=None, hermes_runtime=None):
        self.registry = registry
        self.hermes_enabled = bool(hermes_runtime is not None or Config.HERMES_ENABLED)
        self.hermes = hermes_runtime or HermesRuntimeManager()
        self._lock = threading.RLock()
        self._hermes_tools = []
        self._hermes_discovered = False
        self._last_error = ""

    def refresh(self):
        """Refresh external metadata during an explicit maintenance scan.

        GUI status snapshots run every few seconds and must never create a
        process.  Hermes discovery is therefore opt-in and its result is
        copied into a small in-memory cache for subsequent status reads.
        """
        if not self.hermes_enabled:
            return []
        try:
            discovered = self.hermes.discover_tools()
            tools = [dict(item) for item in discovered if isinstance(item, dict)]
            error = getattr(self.hermes, "last_error", "")
        except Exception as exc:
            tools = []
            error = str(exc)
        with self._lock:
            self._hermes_tools = tools
            self._hermes_discovered = True
            self._last_error = error
            return [dict(item) for item in self._hermes_tools]

    def snapshot(self, *, refresh=False):
        if refresh:
            self.refresh()
        records = []
        if self.registry is not None:
            for record in self.registry.snapshot():
                records.append({"id": f"jarvis.{record.capability_id}", "engine": "JARVIS",
                    "operation": record.operation, "description": record.description,
                    "status": record.status, "risk": record.risk, "permission": record.permission})
        if self.hermes_enabled:
            with self._lock:
                records.extend(dict(item) for item in self._hermes_tools)
        return records

    def report(self, *, refresh=False):
        tools = self.snapshot(refresh=refresh)
        with self._lock:
            discovered = self._hermes_discovered
            last_error = self._last_error
        return {"total": len(tools), "jarvis": sum(t["engine"] == "JARVIS" for t in tools),
                "hermes": sum(t["engine"] == "HERMES" for t in tools), "tools": tools,
                "hermes_discovered": discovered, "last_error": last_error}
