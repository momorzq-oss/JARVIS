from brain.hermes_runtime_manager import HermesRuntimeManager
from core.unified_tool_catalog import UnifiedToolCatalog
from core.unified_tool_router import UnifiedToolRouter


def test_router_prefers_native_windows_and_hybrid_research():
    router = UnifiedToolRouter()
    assert router.choose("Open Word") == "JARVIS"
    assert router.choose("Research this and create a Word report") == "HYBRID"
    assert router.choose("Build this application in the background") == "HERMES"


def test_catalog_uses_namespaces_for_both_engines():
    class Registry:
        def snapshot(self):
            return [type("R", (), {"capability_id": "windows.open_application", "operation": "open_application", "description": "", "status": "WORKING", "risk": "low", "permission": "SAFE_READ"})()]
    class Hermes:
        def discover_tools(self):
            return [{"id": "hermes.todo", "engine": "HERMES"}]
    catalog = UnifiedToolCatalog(Registry(), Hermes())
    # Routine snapshots are process-free and contain only cached metadata.
    assert {tool["id"] for tool in catalog.snapshot()} == {"jarvis.windows.open_application"}
    tools = catalog.snapshot(refresh=True)
    assert {tool["id"] for tool in tools} == {"jarvis.windows.open_application", "hermes.todo"}


def test_catalog_status_uses_cached_hermes_metadata_without_rediscovery():
    class Registry:
        def snapshot(self):
            return []

    class Hermes:
        last_error = ""

        def __init__(self):
            self.calls = 0

        def discover_tools(self):
            self.calls += 1
            return [{"id": "hermes.todo", "engine": "HERMES"}]

    runtime = Hermes()
    catalog = UnifiedToolCatalog(Registry(), runtime)

    assert catalog.report()["hermes"] == 0
    assert runtime.calls == 0
    assert catalog.report(refresh=True)["hermes"] == 1
    assert runtime.calls == 1
    assert catalog.report()["hermes"] == 1
    assert runtime.calls == 1


def test_missing_runtime_is_truthful(tmp_path):
    assert HermesRuntimeManager(home=tmp_path).snapshot()["state"] == "NOT_INSTALLED"
