from types import SimpleNamespace

import pytest

from skills import research


class OfflineLLM:
    available = False
    last_error = "provider unavailable"

    def quick(self, *_args, **_kwargs):
        raise AssertionError("offline local fallback must not call the provider")


def _sources():
    return [
        {
            "title": f"Public source {index}",
            "publisher": "example.test",
            "url": f"https://example.test/{index}",
            "citation_identifier": f"[{index}]",
            "notes": f"Verified evidence from public source {index} about renewable energy.",
        }
        for index in range(1, 4)
    ]


def test_offline_research_builds_a_cited_deterministic_draft(monkeypatch):
    ctx = SimpleNamespace(llm=OfflineLLM())
    monkeypatch.setattr(research, "save_session", lambda _session: None)
    monkeypatch.setattr(
        research, "gather_sources",
        lambda session, *_args, **_kwargs: session.update(sources=_sources()) or session["sources"],
    )

    session = research.build_research_session(
        "renewable energy", ctx, max_sources=3, max_sections=2,
    )

    assert session is not None
    assert len(session["sources"]) == 3
    assert len(session["draft"]) == 2
    assert all("[1]" in section for section in session["draft"].values())
    assert "no generation provider" in session["abstract"]


def test_local_draft_never_claims_success_without_verified_sources():
    session = research._blank_session("renewable energy")
    session["outline"] = ["Current state"]
    ctx = SimpleNamespace(llm=OfflineLLM())

    research.draft_all(session, ctx)

    assert session["draft"] == {"Current state": ""}


def test_hermes_research_read_rejects_private_network_destinations(monkeypatch):
    monkeypatch.setattr(
        research.socket, "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 80))],
    )

    try:
        research.read_source("http://example.test/private")
    except ValueError as exc:
        assert "private" in str(exc)
    else:
        raise AssertionError("private source address was accepted")


def test_hermes_research_wrappers_use_existing_bounded_services(monkeypatch):
    monkeypatch.setattr(
        research, "research_search",
        lambda query, limit: [{"title": query, "url": "https://example.test"}],
    )
    monkeypatch.setattr(
        research.socket, "getaddrinfo",
        lambda host, port: [(
            None, None, None, None,
            (("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34"), port),
        )],
    )
    monkeypatch.setattr(
        research, "_fetch_public_page_text",
        lambda url, max_chars: (url, "Public evidence"),
    )

    assert research.search_web("renewable energy", limit=99) == [{
        "title": "renewable energy", "url": "https://example.test",
    }]
    assert research.read_source("https://example.test") == {
        "url": "https://example.test", "text": "Public evidence",
    }
    assert "Public evidence" in research.summarize_sources([{
        "title": "Source", "url": "https://example.test", "text": "Public evidence",
    }], topic="renewable energy")


def test_hermes_research_read_revalidates_redirect_destination(monkeypatch):
    class Redirect:
        status_code = 302
        headers = {"Location": "http://127.0.0.1/private"}

    monkeypatch.setattr(
        research.socket, "getaddrinfo",
        lambda host, port: [(
            None, None, None, None,
            (("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34"), port),
        )],
    )
    monkeypatch.setattr(research.requests, "get", lambda *_args, **_kwargs: Redirect())

    with pytest.raises(ValueError, match="local|private|non-public"):
        research.read_source("https://example.test/redirect")
