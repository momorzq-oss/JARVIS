import pytest

from brain.router import fast_lane
from core.action_manager import Action, ActionManager
from core.planner import plan_command
from config import Config
from skills.windows_targets import resolve_windows_target


@pytest.mark.parametrize("command,target", [
    ("Open Downloads", "Downloads"),
    ("Open my Downloads folder", "Downloads"),
    ("Show my Downloads", "Downloads"),
    ("Go to Downloads", "Downloads"),
    ("Open Documents", "Documents"),
])
def test_known_folder_routes(command, target):
    intent = fast_lane(command)
    assert intent == {"skill": "app.open_folder", "params": {"target": target}}
    resolved = resolve_windows_target(target, preferred_kind="folder")
    assert resolved is not None
    assert resolved.kind == "folder"


@pytest.mark.parametrize("command,target", [
    ("Open Word", "Word"),
    ("Open Microsoft Word", "Word"),
])
def test_word_application_routes(command, target):
    assert fast_lane(command) == {"skill": "app.open", "params": {"target": target}}


def test_create_word_document_route():
    assert fast_lane("Create a Word document") == {
        "skill": "office_word.create_document", "params": {}
    }


def test_close_routes_use_contextual_resources():
    assert fast_lane("Close it")["params"]["target"] == ""
    assert fast_lane("Close Word")["params"]["target"] == "Word"
    assert fast_lane("Close the folder")["params"]["target"] == "__recent_folder__"
    assert fast_lane("Close everything JARVIS opened")["params"]["target"] == "__all__"
    assert fast_lane("Close the browser.")["skill"] == "browser.close"


def test_downloads_never_resolves_to_word():
    target = resolve_windows_target("Downloads", preferred_kind="folder")
    assert target.kind == "folder"
    assert "winword" not in target.value.lower()


def test_documents_never_resolves_to_word_creation():
    assert fast_lane("Open Documents")["skill"] == "app.open_folder"


def test_word_never_resolves_to_downloads():
    target = resolve_windows_target("Word", preferred_kind="app")
    assert target is not None
    assert target.kind == "app"
    assert "downloads" not in target.value.lower()


def test_live_mode_selection():
    plan = plan_command(
        "Open Word and create a full research report about artificial intelligence. "
        "I want to see you type it."
    )
    assert plan[0]["skill"] == "office_word.create_research_document"
    assert plan[0]["params"]["execution_mode"] == "LIVE_INTERACTIVE"
    assert plan[0]["params"]["report_length"] == "full"


def test_short_live_report_selection():
    intent = fast_lane("Create a short report about renewable energy live in Word")
    assert intent["skill"] == "office_word.create_research_document"
    assert intent["params"]["report_length"] == "short"


def test_open_word_short_live_report_selection():
    intent = fast_lane(
        "Open Word and create a short research report about renewable energy. "
        "Create it live so I can see it."
    )
    assert intent == {
        "skill": "office_word.create_research_document",
        "params": {
            "topic": "renewable energy",
            "execution_mode": "LIVE_INTERACTIVE",
            "report_length": "short",
        },
    }


def test_fast_mode_keeps_existing_research_plan():
    plan = plan_command(
        "Open Microsoft Word and create a research report about cognitive therapy."
    )
    assert plan[0]["skill"] == "app.open_app"
    assert "execution_mode" not in plan[0]["params"]


def test_raw_shell_action_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")
    controller = type("Controller", (), {})()
    manager = ActionManager(controller)
    action = Action("shell", "shell", "execute", {"command": "rm -rf /"})
    with pytest.raises(ValueError, match="Unknown skill"):
        manager.execute_action(action)
