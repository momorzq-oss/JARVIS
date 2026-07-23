from types import SimpleNamespace

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
