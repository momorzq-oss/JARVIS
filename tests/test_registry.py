from core.registry import SessionRegistry, _native_window_closed
from skills.system_control import close_thing


def test_close_recent_closes_newest(tmp_path):
    order = []
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.open_item("app", "First", closer=lambda: order.append("first"))
    registry.open_item("app", "Second", closer=lambda: order.append("second"))
    result = registry.close_recent()
    assert result["entry"]["name"] == "Second"
    assert order == ["second"]


def test_close_by_name_fuzzy_matches(tmp_path):
    closed = []
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.register("browser_tab", "YouTube Music", closer=lambda: closed.append(True))
    results = registry.close_by_name("youtub")
    assert len(results) == 1
    assert results[0]["closed"] is True
    assert closed == [True]


def test_close_all_uses_reverse_order(tmp_path):
    order = []
    registry = SessionRegistry(tmp_path / "registry.json")
    for name in ("one", "two", "three"):
        registry.register("app", name, closer=lambda value=name: order.append(value))
    registry.close_all()
    assert order == ["three", "two", "one"]
    assert registry.get_status() == []


def test_close_everything_reports_empty_registry(tmp_path):
    registry = SessionRegistry(tmp_path / "registry.json")
    ctx = type("Context", (), {"registry": registry})()
    assert close_thing("__all__", ctx) == "There's nothing open at the moment, sir."


def test_previous_runtime_entries_are_not_owned_after_restart(tmp_path):
    path = tmp_path / "registry.json"
    first = SessionRegistry(path)
    first.register("app", "Notepad", pid=12345)
    second = SessionRegistry(path)
    assert second.get_status() == []
    assert second.close_all() == []


def test_discard_types_removes_closed_runtime_resources_without_closer(tmp_path):
    called = []
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.register("browser", "Browser", closer=lambda: called.append(True))
    registry.register("browser_tab", "Google", closer=lambda: called.append(True))
    registry.register("app", "Calculator")

    assert registry.discard_types({"browser", "browser_tab"}) == 2
    assert called == []
    assert [entry["name"] for entry in registry.list_open()] == ["Calculator"]


def test_failed_close_retains_resource_for_truthful_retry(tmp_path):
    registry = SessionRegistry(tmp_path / "registry.json")
    entry = registry.register(
        "document", "Unverified.xlsx",
        extra={"close_policy": "unverified_ownership"},
    )

    result = registry.close_by_name("Unverified.xlsx")

    assert result[0]["closed"] is False
    assert registry.list_open()[0]["id"] == entry["id"]


def test_hidden_appframe_counts_as_closed_without_killing_shared_host():
    class User32:
        def IsWindow(self, _hwnd):
            return True

        def IsWindowVisible(self, _hwnd):
            return False

    assert _native_window_closed(User32(), 1001) is True


def test_verified_window_failure_does_not_fallback_to_pid_or_title(tmp_path, monkeypatch):
    registry = SessionRegistry(tmp_path / "registry.json")
    entry = registry.register(
        "app", "Calculator", pid=999999, hwnd=999999,
        window_title="Calculator",
        extra={"terminate_pid_on_close": False},
    )
    monkeypatch.setattr(
        "psutil.Process",
        lambda _pid: (_ for _ in ()).throw(AssertionError("PID fallback used")),
    )
    monkeypatch.setattr(
        "pygetwindow.getWindowsWithTitle",
        lambda _title: (_ for _ in ()).throw(AssertionError("title fallback used")),
    )
    monkeypatch.setattr("core.registry._native_window_closed", lambda *_args: False)

    assert registry._close_entry(entry) is False


def test_already_closed_verified_window_is_successful_cleanup(tmp_path, monkeypatch):
    registry = SessionRegistry(tmp_path / "registry.json")
    entry = registry.register("app", "Calculator", pid=None, hwnd=999999)

    assert registry._close_entry(entry) is True
