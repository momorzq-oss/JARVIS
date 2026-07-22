"""One namespaced catalog for JARVIS-native and official Hermes tools."""
from __future__ import annotations

from brain.hermes_runtime_manager import HermesRuntimeManager


class UnifiedToolCatalog:
    def __init__(self, registry=None, hermes_runtime=None):
        self.registry = registry
        self.hermes = hermes_runtime or HermesRuntimeManager()

    def snapshot(self):
        records = []
        if self.registry is not None:
            for record in self.registry.snapshot():
                records.append({"id": f"jarvis.{record.capability_id}", "engine": "JARVIS",
                    "operation": record.operation, "description": record.description,
                    "status": record.status, "risk": record.risk, "permission": record.permission})
        records.extend(self.hermes.discover_tools())
        return records

    def report(self):
        tools = self.snapshot()
        return {"total": len(tools), "jarvis": sum(t["engine"] == "JARVIS" for t in tools),
                "hermes": sum(t["engine"] == "HERMES" for t in tools), "tools": tools}
