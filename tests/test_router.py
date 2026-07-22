import pytest

from brain.router import fast_lane


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
    ("time please", "smalltalk", {"kind": "time"}),
    ("what is the date", "smalltalk", {"kind": "date"}),
    ("tell me the date", "smalltalk", {"kind": "date"}),
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
]


@pytest.mark.parametrize("command,skill,params", CASES)
def test_fast_lane_commands(command, skill, params):
    intent = fast_lane(command)
    assert intent is not None
    assert intent["skill"] == skill
    for key, value in params.items():
        assert intent["params"].get(key) == value
