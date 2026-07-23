from skills.browser import BrowserEngine


def test_browser_launch_candidates_have_a_bounded_startup_timeout(monkeypatch, tmp_path):
    observed = []

    class Chromium:
        def launch_persistent_context(self, *_args, **kwargs):
            observed.append(kwargs)
            return object()

    engine = BrowserEngine(registry=None)
    engine.profile_dir = str(tmp_path)
    engine._pw = type("Playwright", (), {"chromium": Chromium()})()
    monkeypatch.setattr("skills.browser.detect_browser_executables", lambda: [None])

    engine._launch()

    assert observed[0]["timeout"] == 30000


def test_teardown_ends_owned_browser_and_driver_without_blocking_protocol_calls(monkeypatch):
    events = []

    class Context:
        def close(self, **_kwargs):
            raise AssertionError("blocking context.close must not be used")

    class Playwright:
        def stop(self):
            raise AssertionError("blocking playwright.stop must not be used")

    engine = BrowserEngine(registry=None)
    engine._context = Context()
    engine._pw = Playwright()
    monkeypatch.setattr(
        engine,
        "_terminate_owned_browser_processes",
        lambda: events.append("owned-processes"),
    )
    monkeypatch.setattr(
        engine,
        "_terminate_driver_process",
        lambda: events.append("driver"),
    )

    engine._teardown_pw()

    assert events == ["owned-processes", "driver"]
    assert engine._context is None
    assert engine._pw is None
