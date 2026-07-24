from types import SimpleNamespace

from core.conversation import (
    CONVERSATION_LISTENING,
    INTENT_EXIT,
    INTENT_FOLLOW_UP,
    INTENT_WEB_TASK,
    ConversationManager,
    ConversationSettings,
)
from core.settings import SettingsStore


def test_conversation_settings_load_from_existing_store(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.update({
        "conversation_mode_enabled": True,
        "followup_listening_enabled": True,
        "barge_in_enabled": True,
        "silence_detection_seconds": 1.8,
        "conversation_memory_limit": 12,
    })

    settings = ConversationSettings.from_store(store)

    assert settings.enabled is True
    assert settings.follow_up_listening is True
    assert settings.barge_in is True
    assert settings.silence_detection_seconds == 1.8
    assert settings.memory_limit == 12


def test_barge_in_is_opt_in_by_default(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")

    settings = ConversationSettings.from_store(store)

    assert settings.barge_in is False
    assert settings.echo_suppression is True


def test_conversation_manager_detects_exit_phrases():
    manager = ConversationManager()

    intent = manager.classify("Thank you Jarvis, that is all.", SimpleNamespace())

    assert intent.intent_type == INTENT_EXIT


def test_conversation_manager_keeps_commands_on_deterministic_tool_route():
    manager = ConversationManager()
    ctx = SimpleNamespace(state={}, pending=None)

    intent = manager.classify("Open YouTube.", ctx)

    assert intent.intent_type == INTENT_WEB_TASK
    assert intent.route["selected_engine"] == "deterministic"
    assert intent.route["intent"]["skill"] == "browser.open_site"


def test_pending_workflow_reply_stays_connected_to_existing_pipeline():
    manager = ConversationManager()
    ctx = SimpleNamespace(state={}, pending={"kind": "research"})

    intent = manager.classify("Use the second source.", ctx)

    assert intent.intent_type == INTENT_FOLLOW_UP
    assert intent.route["route_type"] == "pending"


def test_conversation_session_summarizes_older_messages():
    manager = ConversationManager(ConversationSettings(memory_limit=4))
    manager.begin(user_text="I want to plan a desktop assistant.")
    for index in range(12):
        manager.record_assistant(f"Question {index}?")
        manager.record_user(f"Answer {index}")

    messages, summary = manager.messages_for_model()

    assert len(messages) <= 8
    assert "older messages summarized" in summary
    assert manager.snapshot()["conversation_state"] == CONVERSATION_LISTENING
