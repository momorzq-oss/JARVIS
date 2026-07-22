from core.capability_registry import CapabilityRegistry


def test_registry_discovers_real_skills():
    registry = CapabilityRegistry()
    records = registry.discover()
    ids = {record.capability_id for record in records}
    assert "system_control.handle" in ids
    assert "word_skill.create_document" in ids


def test_registry_includes_approved_operations():
    registry = CapabilityRegistry()
    records = registry.discover()
    by_id = {record.capability_id: record for record in records}
    assert by_id["windows.open_folder"].permission == "SAFE_READ"
    assert by_id["office_word.create_document"].permission == "OFFICE_EDIT"
    assert by_id["desktop.organize"].permission == "FILE_MODIFY"
    assert by_id["system.shutdown"].permission == "SYSTEM_POWER"


def test_adapter_backed_office_and_website_capabilities_are_not_missing():
    registry = CapabilityRegistry()
    records = {record.capability_id: record for record in registry.discover()}
    assert records["office.create_document"].status != "MISSING"
    assert records["website.gmail_search"].status != "MISSING"


def test_every_registered_intent_has_permission_scope():
    registry = CapabilityRegistry()
    by_id = {record.capability_id: record for record in registry.discover()}
    from core.action_manager import ActionManager
    for full_skill in ActionManager.INTENT_ALLOWLIST:
        assert by_id[full_skill].permission != "UNASSIGNED"


def test_registry_health_failures_degrade_not_crash(monkeypatch):
    registry = CapabilityRegistry()
    registry.discover()
    monkeypatch.setattr("core.capability_registry.CapabilityHealth.check",
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("health failed")))
    records = registry.run_health_checks()
    assert records
    assert all(record.status == "DEGRADED" for record in records)


def test_registry_text_comes_from_discovered_records():
    registry = CapabilityRegistry()
    registry.discover()
    assert "system_control" in registry.skills_text()
    assert "windows.open_folder" in registry.capabilities_text()
