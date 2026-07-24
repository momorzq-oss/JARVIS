import sys
import types

import pytest

from brain.router import Router, fast_lane


CASES = [
    ("Jarvis stop", "system.stop_speech", {}),
    ("volume up", "system.volume", {"action": "up"}),
    ("make it louder", "system.volume", {"action": "up"}),
    ("volume down", "system.volume", {"action": "down"}),
    ("mute", "system.volume", {"action": "mute"}),
    ("unmute the sound", "system.volume", {"action": "unmute"}),
    ("take a screenshot", "system.screenshot", {}),
    ("lock the computer", "system.lock", {}),
    ("cancel the shutdown", "system.shutdown", {"action": "cancel"}),
    ("restart the computer", "system.shutdown", {"action": "restart"}),
    ("put the computer to sleep", "system.shutdown", {"action": "sleep"}),
    ("shut down the pc", "system.shutdown", {"action": "shutdown"}),
    ("system status", "system.status", {}),
    ("what time is it", "smalltalk", {"kind": "time"}),
    ("Jarvis, can you tell me the current time now?", "smalltalk", {"kind": "time"}),
    ("Tell me the current time, please.", "smalltalk", {"kind": "time"}),
    ("Could you tell me the current time?", "smalltalk", {"kind": "time"}),
    ("time please", "smalltalk", {"kind": "time"}),
    ("what is the date", "smalltalk", {"kind": "date"}),
    ("what is the date today", "smalltalk", {"kind": "date"}),
    ("could you tell me the current day now", "smalltalk", {"kind": "date"}),
    ("tell me the date", "smalltalk", {"kind": "date"}),
    ("Please tell me the date.", "smalltalk", {"kind": "date"}),
    ("pause the music", "media.control", {"action": "pause"}),
    ("resume music", "media.control", {"action": "resume"}),
    ("next song", "media.control", {"action": "next"}),
    ("mute the music", "media.control", {"action": "mute"}),
    ("stop the music", "media.control", {"action": "stop"}),
    ("play some music", "media.play_music", {"query": ""}),
    ("play Back in Black on YouTube", "media.play_music", {"query": "Back in Black"}),
    ("close it", "app.close", {"target": ""}),
    ("close everything you opened", "app.close", {"target": "__all__"}),
    ("close the browser", "browser.close", {"target": "browser"}),
    ("close YouTube", "browser.close_tab", {"target": "youtube"}),
    ("open calculator", "app.open", {"target": "calculator"}),
    ("check my email", "email.check", {}),
    ("latest news", "news.latest", {}),
    ("news about technology", "news.topic", {"topic": "technology"}),
    ("organize my desktop", "desktop.organize", {}),
    ("undo the organization", "desktop.undo", {}),
    ("search for Python packaging", "web.search", {"query": "Python packaging"}),
    ("remember that my meeting is Friday", "chat", {"remember": "my meeting is Friday"}),
    ("hello Jarvis", "smalltalk", {"kind": "greeting"}),
    ("thanks Jarvis", "smalltalk", {"kind": "thanks"}),
    ("how are you doing", "smalltalk", {"kind": "howareyou"}),
    ("good night Jarvis", "smalltalk", {"kind": "goodbye"}),
    ("start voice", "system.voice_start", {}),
    ("stop listening", "system.voice_stop", {}),
    ("start the microphone", "system.voice_start", {}),
]


@pytest.mark.parametrize("command,skill,params", CASES)
def test_fast_lane_commands(command, skill, params):
    intent = fast_lane(command)
    assert intent is not None
    assert intent["skill"] == skill
    for key, value in params.items():
        assert intent["params"].get(key) == value


def test_local_router_loads_directly_on_cpu_without_disk_offload(monkeypatch):
    calls = {}

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, model_name):
            calls["tokenizer"] = model_name
            return cls()

    class FakeLoadedModel:
        def eval(self):
            calls["eval"] = True

    class FakeModelFactory:
        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            calls["model"] = model_name
            calls["options"] = kwargs
            return FakeLoadedModel()

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.float32 = "float32"
    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoModelForCausalLM = FakeModelFactory
    fake_transformers.AutoTokenizer = FakeTokenizer

    monkeypatch.setattr("brain.router.Config.LOCAL_ROUTER_ENABLED", True)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    router = Router("local-test-model")

    assert router._ensure_loaded() is True
    assert calls["options"]["torch_dtype"] == "float32"
    assert "device_map" not in calls["options"]
    assert calls["eval"] is True
