"""Settings store load/save tests."""
from core.settings import SettingsStore, DEFAULTS


def test_defaults_present(tmp_path):
    store = SettingsStore(tmp_path / "config.json")
    data = store.as_dict()
    for key in ("microphone_device", "wake_threshold", "whisper_model",
                "openrouter_model", "minimize_to_tray", "reduce_motion"):
        assert key in data


def test_save_and_reload(tmp_path):
    path = tmp_path / "config.json"
    store = SettingsStore(path)
    store.set("wake_threshold", 0.7)
    store.set("reduce_motion", True)
    store.save()
    reloaded = SettingsStore(path)
    assert reloaded.get("wake_threshold") == 0.7
    assert reloaded.get("reduce_motion") is True


def test_update_ignores_unknown_keys(tmp_path):
    store = SettingsStore(tmp_path / "config.json")
    store.update({"wake_threshold": 0.9, "not_a_real_key": "x"})
    assert store.get("wake_threshold") == 0.9
    assert "not_a_real_key" not in store.as_dict()


def test_unknown_key_raises(tmp_path):
    store = SettingsStore(tmp_path / "config.json")
    try:
        store.set("bogus", 1)
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_no_api_key_in_defaults():
    blob = " ".join(DEFAULTS.keys()).lower()
    assert "api" not in blob and "key" not in blob


def test_hermes_defaults_match_supported_safe_runtime_modes():
    assert DEFAULTS["hermes_mode"] in {"cli", "disabled"}
    assert DEFAULTS["hermes_background_enabled"] is False
    assert DEFAULTS["hermes_schedules_enabled"] is False
    assert DEFAULTS["hermes_learning_enabled"] is False
    assert DEFAULTS["hermes_approval_mode"] == "strict"
    assert DEFAULTS["hermes_concurrency_limit"] == 2


def test_legacy_managed_hermes_settings_are_repaired_to_disabled(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"hermes_enabled": true, "hermes_mode": "managed", '
        '"hermes_background_enabled": true}',
        encoding="utf-8",
    )

    store = SettingsStore(path)

    assert store.get("hermes_enabled") is False
    assert store.get("hermes_mode") == "disabled"
    assert store.get("hermes_background_enabled") is False


def test_unsafe_hermes_approval_and_concurrency_settings_are_repaired(tmp_path):
    import json

    path = tmp_path / "config.json"
    path.write_text(
        '{"hermes_approval_mode":"trusted_session",'
        '"hermes_concurrency_limit":4}',
        encoding="utf-8",
    )

    store = SettingsStore(path)

    assert store.get("hermes_approval_mode") == "strict"
    assert store.get("hermes_concurrency_limit") == 2
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["hermes_approval_mode"] == "strict"
    assert saved["hermes_concurrency_limit"] == 2


def test_legacy_hermes_model_is_migrated_and_persisted(tmp_path):
    import json

    from config import Config

    path = tmp_path / "config.json"
    path.write_text(
        '{"hermes_model": "openai/gpt-oss-120b"}',
        encoding="utf-8",
    )

    store = SettingsStore(path)

    assert store.get("hermes_model") == "openai/gpt-oss-safeguard-20b"
    assert store.get("hermes_model") == Config.OPENROUTER_MODEL
    assert json.loads(path.read_text(encoding="utf-8"))["hermes_model"] == (
        "openai/gpt-oss-safeguard-20b"
    )
