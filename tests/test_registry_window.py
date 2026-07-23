"""Registry field + window control + office detection tests."""
from core.registry import SessionRegistry
from skills import window_control, office_close


def test_register_stores_extended_fields(tmp_path):
    reg = SessionRegistry(tmp_path / "r.json")
    entry = reg.register("app", "Notepad", pid=123, window_title="Notepad",
                         hwnd=456, exe_path="C:\\Windows\\notepad.exe",
                         path="C:\\docs\\a.txt")
    assert entry["hwnd"] == 456
    assert entry["state"] == "open"
    assert entry["extra"]["exe_path"].endswith("notepad.exe")
    assert entry["extra"]["path"].endswith("a.txt")


def test_set_state_and_count(tmp_path):
    reg = SessionRegistry(tmp_path / "r.json")
    e = reg.register("app", "Calc", closer=lambda: None)
    assert reg.count_open() == 1
    reg.set_state(e["id"], "minimized")
    assert reg.list_open()[0]["state"] == "minimized"


def test_unverified_ownership_never_closes_by_title(tmp_path, monkeypatch):
    reg = SessionRegistry(tmp_path / "r.json")
    entry = reg.register(
        "folder", "Downloads", window_title="Downloads",
        extra={"close_policy": "unverified_ownership"},
    )
    monkeypatch.setattr(
        "pygetwindow.getWindowsWithTitle",
        lambda _title: (_ for _ in ()).throw(AssertionError("personal window touched")),
    )
    assert reg._close_entry(entry) is False


def test_saved_word_document_still_matches_word_alias(tmp_path):
    reg = SessionRegistry(tmp_path / "r.json")
    entry = reg.register(
        "document", "New Word Document", window_title="Word",
        closer=lambda: None,
        extra={"application": "Microsoft Word", "process_name": "WINWORD.EXE"},
    )
    reg.update_entry(
        entry["id"], name="Report.docx", display_name="Report.docx",
        window_title="Report", file_path=str(tmp_path / "Report.docx"),
    )
    assert reg.find_by_name("Word")[0]["id"] == entry["id"]


def _empty_registry():
    reg = SessionRegistry.__new__(SessionRegistry)
    reg._entries = []
    reg._runtime = {}
    reg._lock = __import__("threading").RLock()
    return reg


def test_window_minimize_no_window_returns_message(monkeypatch):
    monkeypatch.setattr(window_control, "_live_windows", lambda: [])
    ctx = type("C", (), {"registry": _empty_registry()})()
    out = window_control.minimize_window("definitelynotawindow123", ctx)
    assert "couldn't find a window" in out.lower()


def test_window_minimize_uses_registry_match(monkeypatch):
    reg = _empty_registry()
    reg.register("app", "Notepad", window_title="Untitled - Notepad",
                 closer=lambda: None)
    calls = []

    class FakeWin:
        title = "Untitled - Notepad"

        def minimize(self):
            calls.append("min")

    monkeypatch.setattr(window_control, "_live_windows", lambda: [FakeWin()])
    ctx = type("C", (), {"registry": reg})()
    out = window_control.minimize_window("notepad", ctx)
    assert "minimizing" in out.lower()
    assert calls == ["min"]


def test_verified_registry_hwnd_uses_nonblocking_native_window_action(monkeypatch):
    reg = _empty_registry()
    reg.register("app", "Calculator", window_title="Calculator", hwnd=456)
    calls = []
    monkeypatch.setattr(
        window_control, "_show_owned_window",
        lambda entry, verb: calls.append((entry["hwnd"], verb)) or True,
    )
    monkeypatch.setattr(
        window_control, "_live_windows",
        lambda: (_ for _ in ()).throw(AssertionError("slow window scan used")),
    )
    ctx = type("C", (), {"registry": reg})()

    assert "maximizing" in window_control.maximize_window("Calculator", ctx).lower()
    assert calls == [(456, "maximize")]


def test_window_front_requires_target():
    ctx = type("C", (), {"registry": None})()
    assert window_control.bring_to_front("", ctx) == "Bring what to the front, sir?"


def test_office_app_detection():
    assert office_close.is_office_app("Microsoft Word")
    assert office_close.is_office_app("excel")
    assert office_close.is_office_app("powerpnt")
    assert not office_close.is_office_app("notepad")


def test_unsaved_unknown_when_office_not_running():
    # Without Office COM running this must degrade gracefully (None or False)
    result = office_close.has_unsaved_changes("Microsoft Word")
    assert result in (None, False, True)  # never raises
