from types import SimpleNamespace

from skills import research


def test_llm_topic_is_disambiguated_for_retrieval_but_preserves_display_title():
    session = research._blank_session("local LLM education")

    assert session["topic"] == "local LLM education"
    assert session["semantic_topic"] == (
        "local large language model (LLM) education"
    )


def test_explicit_master_of_laws_topic_is_not_rewritten():
    topic = "local LLM law degree options"
    assert research.clarify_research_topic(topic) == topic


def test_source_filter_rejects_legal_homonym_and_accepts_ai_sources():
    session = research._blank_session("local LLM education")

    assert not research._source_matches_context(session, {
        "title": "Legal education in Hong Kong",
        "snippet": "Law schools and the Master of Laws degree.",
        "url": "https://example.test/legal-education",
    })
    assert research._source_matches_context(session, {
        "title": "Large language model",
        "snippet": "Artificial intelligence language models can run locally.",
        "url": "https://example.test/large-language-model",
    })
    assert research._source_matches_context(session, {
        "title": "Ollama",
        "snippet": "A tool for running large language models on local computers.",
        "url": "https://example.test/ollama",
    })


def test_research_session_requires_three_verified_sources(monkeypatch):
    class LLM:
        available = True
        last_error = ""

        def quick(self, *_args, **_kwargs):
            return "1. Background - context\n2. Practice - examples\n3. Risks - limits"

    ctx = SimpleNamespace(llm=LLM())
    monkeypatch.setattr(research, "save_session", lambda _session: None)
    monkeypatch.setattr(
        research,
        "gather_sources",
        lambda *_args, **_kwargs: [{"title": "Only one source"}],
    )

    assert research.build_research_session("local LLM education", ctx) is None
