from core.capability_health import (
    CapabilityHealth, DEGRADED, REQUIRES_CONFIGURATION,
    REQUIRES_LOGIN, WORKING,
)


def test_system_metrics_do_not_import_process_telemetry(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "psutil":
            raise AssertionError("routine metrics must not import psutil")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    metrics = CapabilityHealth().system_metrics()

    assert metrics["status"] == "WORKING"
    assert "ram_percent" in metrics
    assert "disk_percent" in metrics


def test_health_reports_working_for_builtin_skill():
    result = CapabilityHealth().check("system_control")
    assert result.status == WORKING


def test_health_reports_missing_configuration(monkeypatch):
    monkeypatch.setattr("core.capability_health.Config.OPENROUTER_API_KEY", "")
    result = CapabilityHealth().check("coder")
    assert result.status == REQUIRES_CONFIGURATION
    assert "OPENROUTER_API_KEY" in result.detail


def test_health_rejects_placeholder_openrouter_key(monkeypatch):
    monkeypatch.setattr(
        "core.capability_health.Config.OPENROUTER_API_KEY", "your_key_here"
    )
    result = CapabilityHealth().check("coder")
    assert result.status == REQUIRES_CONFIGURATION


def test_chat_health_accepts_saved_openrouter_key(monkeypatch):
    monkeypatch.setattr("core.capability_health.Config.OPENROUTER_API_KEY", "")
    monkeypatch.setattr(
        "core.secret_store.load_openrouter_key",
        lambda: "sk-or-v1-regression-key",
    )

    result = CapabilityHealth().check("chat")

    assert result.status == WORKING
    assert "OpenRouter" in result.detail


def test_chat_health_accepts_local_qwen(monkeypatch):
    monkeypatch.setattr("core.capability_health.Config.OPENROUTER_API_KEY", "")
    monkeypatch.setattr("core.secret_store.load_openrouter_key", lambda: "")
    monkeypatch.setattr("core.capability_health.Config.COLIBRI_ENABLED", False)
    monkeypatch.setattr("core.capability_health.Config.LOCAL_ROUTER_ENABLED", True)
    monkeypatch.setattr(
        "core.capability_health.importlib.util.find_spec",
        lambda _name: object(),
    )

    result = CapabilityHealth().check("chat")

    assert result.status == WORKING
    assert "Local" in result.detail


def test_health_reports_login_requirement():
    result = CapabilityHealth().check("gmail")
    assert result.status == REQUIRES_LOGIN


def test_health_check_failure_is_degraded(monkeypatch):
    monkeypatch.setattr("core.capability_health.importlib.util.find_spec",
                        lambda name: None)
    result = CapabilityHealth().check("browser")
    assert result.status == DEGRADED
