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
    tools = UnifiedToolCatalog(Registry(), Hermes()).snapshot()
    assert {tool["id"] for tool in tools} == {"jarvis.windows.open_application", "hermes.todo"}


def test_missing_runtime_is_truthful(tmp_path):
    assert HermesRuntimeManager(home=tmp_path).snapshot()["state"] == "NOT_INSTALLED"
