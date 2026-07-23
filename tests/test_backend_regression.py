from pathlib import Path

import main
from brain.router import fast_lane
from core.command_text import cleanup_command
from core.planner import plan_command
from skills import system_control
from skills.browser import detect_browser_executable, detect_browser_executables
from skills.windows_targets import resolve_windows_target
from config import Config


class FakeRegistry:
    def __init__(self):
        self.entries = []

    def register(self, type_, name, **kwargs):
        entry = {"type": type_, "name": name, **kwargs}
        self.entries.append(entry)
        return entry


class FakeBrowser:
    def open_site(self, target, name=None):
        return {"target": target, "name": name}


class FakeSpeaker:
    speaking = False

    def __init__(self):
        self.messages = []

    def speak(self, text, block=False):
        self.messages.append(text)

    def stop(self):
        return None


def fake_context():
    return type("Context", (), {
        "registry": FakeRegistry(),
        "browser": FakeBrowser(),
        "speaker": FakeSpeaker(),
        "pending": None,
        "state": {},
    })()


def test_cleanup_preserves_downloads_request():
    assert cleanup_command("window open my Downloads folder") == "open my Downloads folder"


def test_cleanup_removes_false_starts_and_repetition():
    assert cleanup_command("um server open open Notepad") == "open Notepad"


def test_folder_commands_use_folder_skill():
    for command in (
        "Open my Downloads folder.",
        "Open my Documents folder.",
        "Open my Desktop folder.",
        "Open the JARVIS project folder.",
    ):
        assert fast_lane(command)["skill"] == "app.open_folder"


def test_youtube_commands_have_exact_routes():
    assert fast_lane("Open YouTube.")["skill"] == "browser.open_site"
    intent = fast_lane("Search YouTube for Dangerous Minds song.")
    assert intent == {
        "skill": "browser.search_youtube",
        "params": {"query": "Dangerous Minds song"},
    }


def test_office_and_research_commands_have_exact_routes():
    assert fast_lane("Create a Word document about therapy.")["skill"] == "word.write"
    assert fast_lane("Create an Excel spreadsheet about expenses.")["skill"] == "office.create_spreadsheet"
    assert fast_lane("Create a PowerPoint presentation about safety.")["skill"] == "office.create_presentation"
    assert fast_lane("Create a research report about therapy.")["skill"] == "research.create_report"


def test_file_search_has_exact_route():
    intent = fast_lane("Find file quarterly report.")
    assert intent == {"skill": "app.search_file", "params": {"target": "quarterly report"}}


def test_browser_multistep_plan():
    plan = plan_command(
        "Open the browser, go to YouTube, and search for Dangerous Minds song."
    )
    assert [step["skill"] for step in plan] == [
        "browser.open", "browser.open_site", "browser.search_youtube"
    ]
    assert plan[-1]["params"]["query"] == "Dangerous Minds song"


def test_research_multistep_plan():
    plan = plan_command(
        "Open Microsoft Word and create a research report about cognitive therapy."
    )
    assert [step["skill"] for step in plan] == [
        "app.open_app",
        "research.prepare_report",
        "research.gather_report",
        "research.draft_report",
        "research.finalize_report",
        "research.open_report",
    ]
    assert plan[1]["params"]["topic"] == "cognitive therapy"


def test_known_windows_folders_resolve_to_existing_paths():
    for name in ("Downloads", "Documents", "Desktop", "JARVIS project"):
        target = resolve_windows_target(name)
        assert target is not None
        assert target.kind == "folder"
        assert Path(target.value).is_dir()


def test_absolute_and_relative_paths_resolve(tmp_path, monkeypatch):
    file_path = tmp_path / "report.txt"
    file_path.write_text("ready", encoding="utf-8")
    assert resolve_windows_target(str(file_path)).kind == "file"
    monkeypatch.setattr("skills.windows_targets.Config.SOURCE_DIR", tmp_path)
    assert resolve_windows_target("report.txt").value == str(file_path.resolve())


def test_common_apps_resolve():
    for name in ("Notepad", "Calculator", "Microsoft Word"):
        target = resolve_windows_target(name)
        assert target is not None
        assert target.kind == "app"


def test_folder_launch_registers_only_after_start(monkeypatch, tmp_path):
    ctx = fake_context()
    opened = []

    class ExplorerProcess:
        pid = 456

    def fake_popen(args, **kwargs):
        opened.append((args, kwargs))
        return ExplorerProcess()

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(system_control, "_native_process_ids_by_name", lambda _name: {456})
    monkeypatch.setattr(
        system_control, "_find_new_folder_window",
        lambda *_args, **_kwargs: (123, 456, tmp_path.name),
    )
    result = system_control.open_thing(str(tmp_path), ctx, preferred_kind="folder")
    assert opened[0][0] == ["explorer.exe", str(tmp_path)]
    assert opened[0][1]["shell"] is False
    assert result.startswith("Opening the folder")
    assert ctx.registry.entries[-1]["type"] == "folder"
    assert ctx.registry.entries[-1]["extra"]["path"] == str(tmp_path)


def test_failed_folder_launch_does_not_register(monkeypatch, tmp_path):
    ctx = fake_context()

    def fail(*_args, **_kwargs):
        raise OSError("blocked")

    monkeypatch.setattr(system_control.subprocess, "Popen", fail)
    result = system_control.open_thing(str(tmp_path), ctx, preferred_kind="folder")
    assert "did not open" in result
    assert ctx.registry.entries == []


def test_named_close_never_falls_back_to_unowned_process(monkeypatch):
    ctx = fake_context()
    ctx.registry.close_by_name = lambda _name: []
    monkeypatch.setattr(
        "psutil.process_iter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unowned process scan attempted")
        ),
    )
    result = system_control.close_thing("Word", ctx)
    assert "JARVIS-owned" in result


def test_file_launch_registers_only_after_start(monkeypatch, tmp_path):
    ctx = fake_context()
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello", encoding="utf-8")
    opened = []
    monkeypatch.setattr(system_control.os, "startfile", lambda path: opened.append(path))
    result = system_control.open_thing(str(file_path), ctx, preferred_kind="file")
    assert opened == [str(file_path)]
    assert result.startswith("Opening the file")
    assert ctx.registry.entries[-1]["type"] == "file"


def test_browser_executable_detection_uses_declared_order(tmp_path):
    edge = tmp_path / "edge.exe"
    chrome = tmp_path / "chrome.exe"
    chrome.write_bytes(b"")
    edge.write_bytes(b"")
    assert detect_browser_executable([edge, chrome]) == edge
    assert detect_browser_executables([edge, chrome]) == [edge, chrome]


def test_browser_storage_is_outside_pyinstaller_temp():
    local_jarvis = Path.home() / "AppData" / "Local" / "JARVIS"
    assert Config.BROWSER_PROFILE_DIR == local_jarvis / "browser-profile"
    assert Config.PLAYWRIGHT_BROWSERS_DIR == local_jarvis / "browsers"


def test_handle_utterance_uses_cleaned_text(monkeypatch):
    ctx = fake_context()
    captured = []
    monkeypatch.setattr(main, "dispatch", lambda intent, _ctx: captured.append(intent) or "done")
    result = main.handle_utterance("window open my Downloads folder", ctx)
    assert captured[0]["skill"] == "app.open_folder"
    assert captured[0]["params"]["target"] == "Downloads"
    assert result == "done"
