"""Local browser-intent coverage: no model or cloud service is involved."""
from __future__ import annotations

import pytest

from brain.router import fast_lane
from core.automation_intents import classify_browser_intent


@pytest.mark.parametrize(("command", "skill", "query", "destination"), [
    ("I need to browse the web", "browser.open", "", "browser"),
    ("Launch a browser", "browser.open", "", "browser"),
    ("Bring up Chrome", "browser.open", "", "browser"),
    ("Open Chromecast browser", "browser.open", "", "browser"),
    ("Bring up Google", "browser.open_site", "", "google"),
    ("Look for local LLM education", "web.search", "local LLM education", "google"),
    ("Search for dancing tutorials", "web.search", "dancing", "google"),
    ("Can you find information about quantum computing?", "web.search", "quantum computing", "google"),
    ("Open Google and look up machine learning", "web.search", "machine learning", "google"),
    ("Find me an article about local AI", "web.search", "local AI", "google"),
    ("YouTube local LLM creation", "browser.search_youtube", "local LLM creation", "youtube"),
    ("Look on YouTube for building a local LLM", "browser.search_youtube", "building a local LLM", "youtube"),
    ("Find a video explaining local language models", "browser.search_youtube", "local language models", "youtube"),
    ("Play an educational video about dancing", "browser.search_youtube_and_play", "dancing", "youtube"),
    ("Show me the best tutorial for running an LLM locally", "browser.search_youtube", "running an LLM locally", "youtube"),
    ("Open a new tab and search for quantum computing", "web.search", "quantum computing", "google"),
])
def test_flexible_browser_language_is_local(command, skill, query, destination):
    intent = classify_browser_intent(command)
    assert intent is not None
    assert intent["skill"] == skill
    assert intent["params"]["destination"] == destination
    assert intent["params"].get("query", "") == query


def test_browser_intent_precedes_generic_open_and_search_rules():
    intent = fast_lane("Open Google and look up machine learning")
    assert intent["skill"] == "web.search"
    assert intent["params"]["query"] == "machine learning"
    assert intent["params"]["intent_group"] == "BROWSER_LOCAL"


def test_youtube_context_resolves_a_follow_up_without_a_model():
    state = {"browser_context": {"destination": "youtube", "query": "creating a local LLM"}}
    intent = classify_browser_intent("Play the best one", state)
    assert intent["skill"] == "browser.search_youtube_and_play"
    assert intent["params"]["query"] == "creating a local LLM"
    assert intent["params"]["selection"] == "most_relevant"


@pytest.mark.parametrize(("command", "skill", "target"), [
    ("Close tab", "browser.close_tab", "current"),
    ("Close this tab", "browser.close_tab", "current"),
    ("Close the YouTube tab", "browser.close_tab", "youtube"),
    ("Close the browser", "browser.close", "browser"),
    ("Exit Chrome", "browser.close", "browser"),
])
def test_local_browser_close_variations(command, skill, target):
    intent = classify_browser_intent(command)
    assert intent is not None
    assert intent["skill"] == skill
    assert intent["params"]["target"] == target
