"""Tests for the assistant controller bridge (headless, lightweight ctx)."""
import sys
import os
# Add current directory to path for module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import threading
import time
import pytest
from unittest.mock import Mock, patch

from core.assistant_controller import (
    AssistantController, STATE_IDLE, STATE_LISTENING_WAKE, STATE_PROCESSING,
)
from core.action_manager import Action
from config import Config
from voice.speech_service import SpeechOutputService # Import real SpeechOutputService


class FakeSpeaker:
    speaking = False
    last_engine = "piper"
    spoken = []
    muted = False # Add muted state

    def __init__(self):
        self.spoken = []
        self.muted = False
        self.state_mock = Mock() # Mock the state object passed to Speaker
        self.state_mock.speaker_state = "ready"

    def speak(self, text, block=False):
        if not self.muted and text:
            self.spoken.append(text)

    def stop(self):
        pass

    def wait(self, timeout=None):
        pass

    def mute(self):
        self.muted = True
        self.state_mock.speaker_state = "muted"

    def unmute(self):
        self.muted = False
        self.state_mock.speaker_state = "ready"


class FakeListener:
    _model = object()
    load_error = ""

    def preload(self):
        pass


class FakeRouter:
    load_error = ""

    def preload(self):
        pass


class FakeLLM:
    available = True


class FakeBrowser:
    _page = None

    def close_browser(self):
        return 0


class FakeRegistry:
    def __init__(self):
        self.items = []

    def count_open(self):
        return len(self.items)

    def get_status(self):
        return list(self.items)

    def close_all(self):
        out = list(self.items)
        self.items.clear()
        return out


def make_ctx():
    speaker_instance = FakeSpeaker()
    ctx = type("Ctx", (), {
        "speaker": speaker_instance, # Ensure FakeSpeaker is used
        "listener": FakeListener(),
        "router": FakeRouter(),
        "llm": FakeLLM(),
        "browser": FakeBrowser(),
        "registry": FakeRegistry(),
        "pending": None,
        "debug": False,
        "YES_WORDS": ["yes"],
        "NO_WORDS": ["no"],
        "CANCEL_WORDS": ["cancel"],
        "state": speaker_instance.state_mock # Directly link the state mock
    })()
    # Use a simpler Mock for gui_controller to avoid threading issues in tests
    mock_gui_controller = Mock()
    mock_gui_controller._confirmation_response = threading.Event()
    mock_gui_controller._confirmation_decision = False
    ctx.gui_controller = mock_gui_controller
    return ctx


class FakeVoiceEngine:
    def __init__(self):
        self.running = False
        self.capture = type("C", (), {"device_index": None})()
        self.start_calls = 0

    def set_diagnostic(self, on):
        pass

    def start(self):
        self.start_calls += 1
        self.running = True
        return True

    def stop(self):
        self.running = False


# Removed FakeGuiController class definition as it is now directly mocked in make_ctx

def test_status_snapshot_keys():
    ctl = AssistantController(ctx=make_ctx(), skip_preload=True)
    snap = ctl.status_snapshot()
    for key in ("state", "microphone_active", "selected_microphone",
                "speaker_state", "wakeword_active", "whisper_loaded",
                "openrouter", "browser", "sessions"):
        assert key in snap


def test_handle_text_updates_last_command_and_response(monkeypatch):
    ctx = make_ctx()
    ctl = AssistantController(ctx=ctx, skip_preload=True)
    events = []
    ctl.set_callback("timeline", lambda stage, text: events.append(stage))
    
    monkeypatch.setattr("main.handle_utterance",
                        lambda text, routed_ctx: "Real router result.")

    spoken = ctl.handle_text("open notepad")
    assert ctl._last_command == "open notepad"
    assert spoken == "Real router result."
    assert "heard" in events and "cleaned" in events


def test_registry_command_is_spoken_once_by_controller():
    ctx = make_ctx()
    ctl = AssistantController(ctx=ctx, skip_preload=True)

    spoken = ctl.handle_text("/help")

    assert spoken.startswith("Registry commands:")
    assert ctx.speaker.spoken == [spoken]


def test_start_voice_twice_does_not_recreate_engine(monkeypatch):
    ctx = make_ctx()
    ctl = AssistantController(ctx=ctx, skip_preload=True)
    monkeypatch.setattr("core.assistant_controller.resolve_microphone",
                        lambda saved=None: ({"index": None, "name": "fake-mic"}, "default"))
    fake = FakeVoiceEngine()

    # Patch VoiceEngine creation to return our fake
    with patch('core.assistant_controller.VoiceEngine', return_value=fake):
        assert ctl.start_voice() is True
        assert ctl.voice_running is True
        assert ctl.start_voice() is True          # idempotent, not a 2nd engine
        assert ctl.voice_engine is fake           # reused, not re-created
        assert fake.start_calls == 1              # started once only
        ctl.shutdown()


def test_stop_voice_when_not_running_returns_false():
    ctx = make_ctx()
    ctl = AssistantController(ctx=ctx, skip_preload=True)
    assert ctl.stop_voice() is False


def test_shutdown_stops_voice_engine():
    ctx = make_ctx()
    ctl = AssistantController(ctx=ctx, skip_preload=True)
    fake = FakeVoiceEngine()
    fake.running = True
    ctl.voice_engine = fake
    ctl.shutdown()
    assert ctl.voice_running is False
    assert fake.running is False


def test_speak_uses_speech_service():
    ctx = make_ctx()
    ctl = AssistantController(ctx=ctx, skip_preload=True)
    ctl.speak("Hello, sir.")
    assert "Hello, sir." in ctx.speaker.spoken


def test_mute_unmute_updates_state():
    ctx = make_ctx()
    ctl = AssistantController(ctx=ctx, skip_preload=True)
    ctl.mute_speech()
    assert ctl.speech_muted is True
    assert ctl.state.speaker_state == "muted"
    ctl.unmute_speech()
    assert ctl.speech_muted is False
    assert ctl.state.speaker_state == "ready"


def test_muted_speech_is_suppressed():
    ctx = make_ctx()
    ctl = AssistantController(ctx=ctx, skip_preload=True)
    ctl.mute_speech()
    ctl.speak("Should not be spoken")
    assert "Should not be spoken" not in ctx.speaker.spoken


# New tests for confirmation flow integration.
def test_confirmation_requested_and_approved(monkeypatch):
    ctx = make_ctx()
    # Set gui_controller to a mock with predefined confirmation_decision
    ctx.gui_controller._confirmation_decision = True
    ctl = AssistantController(ctx=ctx, skip_preload=True)
    
    # Mock agent.confirm to directly use gui_controller's decision
    def mock_agent_confirm(action: Action):
        return ctx.gui_controller._confirmation_decision
    monkeypatch.setattr(ctl.agent, 'confirm', mock_agent_confirm)

    monkeypatch.setattr(ctl.action_manager, "_execute_registered",
                        lambda action: "Closed JARVIS-owned resources.")
    action = Action("approved", "windows", "close_all_jarvis_items", {},
                    requires_confirmation=True)
    result = ctl.action_manager.execute_action(action)
    assert result == "Closed JARVIS-owned resources."
    assert "Sir, I need confirmation to close_all_jarvis_items." in ctx.speaker.spoken
    assert "Action denied, sir." not in ctx.speaker.spoken

def test_confirmation_requested_and_denied(monkeypatch):
    ctx = make_ctx()
    # Set gui_controller to a mock with predefined confirmation_decision
    ctx.gui_controller._confirmation_decision = False
    ctl = AssistantController(ctx=ctx, skip_preload=True)

    # Mock agent.confirm to directly use gui_controller's decision
    def mock_agent_confirm(action: Action):
        return ctx.gui_controller._confirmation_decision
    monkeypatch.setattr(ctl.agent, 'confirm', mock_agent_confirm)

    monkeypatch.setattr(ctl.action_manager, "_execute_registered",
                        lambda action: pytest.fail("Denied action executed"))
    action = Action("denied", "windows", "close_all_jarvis_items", {},
                    requires_confirmation=True)
    result = ctl.action_manager.execute_action(action)
    assert result == "Action denied by user."
    assert "Sir, I need confirmation to close_all_jarvis_items." in ctx.speaker.spoken
    assert "Action denied, sir." in ctx.speaker.spoken # Use ctx.speaker.spoken
    


def test_desktop_agent_confirm_no_handler_logs_error(monkeypatch):
    ctx = make_ctx()
    ctl = AssistantController(ctx=ctx, skip_preload=True)
    ctl.agent._confirm_handler = None  # Ensure no handler is set
    action = Action(action_id="1", skill="test", operation="delete_all", parameters={},
                    requires_confirmation=True)
    
    # We need to mock audio_log.log to capture the expected log message
    mock_log_error = Mock()
    monkeypatch.setattr('voice.audio_log.log_error', mock_log_error)
    mock_log = Mock()
    monkeypatch.setattr('voice.audio_log.log', mock_log)

    # Directly call agent.confirm, which controller.confirm eventually calls
    result = ctl.confirm(action)
    assert result is False
    mock_log.assert_any_call(f"[agent] confirmation required but no handler: {action.action_id}")

# Test voice confirmation handling
def test_voice_confirmation_yes(monkeypatch):
    import main
    ctx = make_ctx()
    called = []
    ctx.pending = {"kind": "confirm", "on_yes": lambda: called.append(True) or "done"}
    handled, result = main.handle_pending("yes", ctx)
    assert handled is True
    assert result == "done"
    assert called == [True]


def test_voice_confirmation_no(monkeypatch):
    import main
    ctx = make_ctx()
    ctx.pending = {"kind": "confirm", "on_yes": lambda: "wrong",
                   "on_no": lambda: "cancelled"}
    handled, result = main.handle_pending("no", ctx)
    assert handled is True
    assert result == "cancelled"


def test_apply_settings_reconfigures_live_hermes_adapter_safely(monkeypatch):
    ctx = make_ctx()
    ctl = AssistantController(ctx=ctx, skip_preload=True)
    values = {
        "speaker_device": "default",
        "hermes_enabled": True,
        "hermes_mode": "cli",
        "hermes_provider": "openrouter",
        "hermes_model": "openai/gpt-oss-safeguard-20b",
        "hermes_concurrency_limit": 2,
    }
    store = type("Store", (), {"get": lambda self, key, default=None: values.get(key, default)})()
    ctl.attach_settings(store, initialize_audio=False)
    ctl.speech.set_output_device = lambda _device: True
    monkeypatch.setattr(ctl, "status_snapshot", lambda: {})
    for key in (
        "HERMES_ENABLED", "HERMES_MODE", "HERMES_PROVIDER", "HERMES_MODEL",
        "HERMES_MAX_CONCURRENT_TASKS", "HERMES_BACKGROUND_TASKS_ENABLED",
        "HERMES_SCHEDULING_ENABLED", "HERMES_LEARNING_ENABLED",
    ):
        monkeypatch.setattr(Config, key, getattr(Config, key))

    assert ctl.apply_settings() is True
    assert ctl.hermes_adapter.enabled is True
    assert ctl.hermes_adapter.mode == "cli"
    assert ctl.hermes_adapter.provider == "openrouter"
    assert ctl.hermes_adapter.model == "openai/gpt-oss-safeguard-20b"
    assert ctl.hermes_tasks.max_concurrent == 2
    assert Config.HERMES_BACKGROUND_TASKS_ENABLED is False
    assert Config.HERMES_SCHEDULING_ENABLED is False
    assert Config.HERMES_LEARNING_ENABLED is False
