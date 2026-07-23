import json
from types import SimpleNamespace

import pytest

from config import Config
from skills.web_automation import (
    BrowserAutomationService,
    WebActionLogger,
    WebActionResult,
    descriptive_download_name,
    page_domain,
)
from skills.website_adapters import WebsiteAdapterRegistry


class FakePage:
    def __init__(self, url="https://mail.google.com/mail/u/0/#inbox", title="Private Inbox"):
        self.url = url
        self._title = title
        self.evaluated = []

    def title(self):
        return self._title

    def is_closed(self):
        return False

    def evaluate(self, script):
        self.evaluated.append(script)


class FakeBrowser:
    def __init__(self, page):
        self._context = SimpleNamespace(pages=[page])
        self.ensure_calls = 0

    def ensure(self):
        self.ensure_calls += 1
        return True

    @property
    def context(self):
        return self._context


def _service(page=None):
    page = page or FakePage()
    ctx = SimpleNamespace(
        browser=FakeBrowser(page), state={}, live_task=None,
        llm=SimpleNamespace(available=False),
    )
    return BrowserAutomationService(ctx)


def test_domain_verification_requires_expected_host():
    service = _service()
    page = FakePage("https://docs.google.com/document/d/1")
    assert page_domain(page) == "docs.google.com"
    assert service.verify_domain(page, ("google.com",)) is True
    assert service.verify_domain(page, ("stripe.com",)) is False


def test_web_log_redacts_private_page_content_and_title(tmp_path, monkeypatch):
    path = tmp_path / "web.jsonl"
    monkeypatch.setattr(Config, "WEB_ACTION_LOG_FILE", path)
    result = WebActionResult(
        "success", "read_page", "secret private page text",
        website="mail.google.com", page_title="Alice - Inbox",
        data="secret private page text",
    )
    WebActionLogger().write(result, intent="READ_PAGE")
    raw = path.read_text(encoding="utf-8")
    entry = json.loads(raw)
    assert "secret private page text" not in raw
    assert entry["page_title"] == "[PRIVATE PAGE]"
    assert entry["result"] == "Read 24 characters from the active page"


def test_emergency_stop_stops_active_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "WEB_ACTION_LOG_FILE", tmp_path / "web.jsonl")
    page = FakePage("https://example.com", "Example")
    result = _service(page).emergency_stop()
    assert result.status == "success"
    assert page.evaluated == ["window.stop()"]


def test_emergency_stop_does_not_launch_an_offline_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "WEB_ACTION_LOG_FILE", tmp_path / "web.jsonl")
    service = _service()
    service.browser._context = None

    result = service.emergency_stop()

    assert result.status == "success"
    assert service.browser.ensure_calls == 0


def test_website_adapter_registry_is_explicit():
    registry = WebsiteAdapterRegistry(_service())
    assert {"google", "youtube", "gmail", "google drive", "google docs", "google sheets", "google slides", "stripe", "github"} <= set(registry.names())
    with pytest.raises(ValueError, match="Unknown website adapter"):
        registry.get("unknown")


def test_download_filename_is_sanitized():
    assert descriptive_download_name("../report?.pdf") == "report_.pdf"


def test_execute_routes_local_youtube_search_and_play(monkeypatch):
    service = _service()
    expected = WebActionResult("success", "youtube_play_relevant", "Selected local result.")
    observed = {}

    def play(query, selection):
        observed.update(query=query, selection=selection)
        return expected

    monkeypatch.setattr(service, "search_youtube_and_play", play)
    result = service.execute({
        "skill": "browser.search_youtube_and_play",
        "params": {"query": "building a local LLM", "selection": "most_relevant"},
    })

    assert result == "Selected local result."
    assert observed == {"query": "building a local LLM", "selection": "most_relevant"}


def test_youtube_selection_waits_for_a_normal_video_result(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "WEB_ACTION_LOG_FILE", tmp_path / "web.jsonl")
    events = []

    class Candidate:
        def get_attribute(self, name):
            return {"title": "Relaxing Piano Music", "href": "/watch?v=123"}.get(name)

        def inner_text(self):
            return "Relaxing Piano Music"

        def click(self, **_kwargs):
            events.append("click")

    class Candidates:
        def count(self):
            return 1

        def nth(self, _index):
            return Candidate()

    page = FakePage("https://www.youtube.com/results?search_query=relaxing+piano", "YouTube")
    page.wait_for_selector = lambda selector, **kwargs: events.append((selector, kwargs))
    page.locator = lambda selector: Candidates()
    page.wait_for_load_state = lambda *_args, **_kwargs: events.append("loaded")
    service = _service(page)

    result = service.youtube_play_relevant("relaxing piano")

    assert result.status == "success"
    assert events[0] == (
        "ytd-video-renderer a#video-title[href*='/watch']",
        {"state": "attached", "timeout": 15000},
    )
    assert "click" in events


def test_close_named_tab_stays_inside_jarvis_browser_session(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "WEB_ACTION_LOG_FILE", tmp_path / "web.jsonl")
    page = FakePage("https://www.youtube.com/results?search_query=llm", "YouTube: LLM")
    closed = []
    page.close = lambda: closed.append(True)
    service = _service(page)

    result = service.close_tab("youtube")

    assert result.status == "success"
    assert closed == [True]


def test_missing_named_tab_never_closes_unrelated_active_tab(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "WEB_ACTION_LOG_FILE", tmp_path / "web.jsonl")
    page = FakePage("https://www.google.com/search?q=llm", "Google: LLM")
    closed = []
    page.close = lambda: closed.append(True)
    service = _service(page)

    result = service.close_tab("youtube")

    assert result.status == "failed"
    assert "matching youtube" in result.message.lower()
    assert closed == []
