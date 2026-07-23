from pathlib import Path
from types import SimpleNamespace

import pytest

from brain.router import fast_lane
from core.command_pipeline import select_route
from core.live_task import LiveTaskController
from core.university_assignment import (
    classify_assignment_intent,
    missing_essential_details,
    parse_assignment_request,
)
from skills import university_assignment as assignment


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("Write an APA 7 essay about artificial intelligence", "Essay"),
        ("Create an academic business report about market entry using IEEE", "Business Report"),
        ("Prepare milestone two for my university project about solar storage using APA", "Project Milestone"),
        ("Write chapter one of my dissertation about online learning using Chicago", "Dissertation Chapter"),
    ],
)
def test_assignment_type_detection_uses_one_shared_route(phrase, expected):
    intent = fast_lane(phrase, {})
    assert intent["skill"] == "university.assignment"
    assert intent["params"]["assignment_type"] == expected


def test_assignment_metadata_extraction():
    data = parse_assignment_request(
        "Write a 2,000-word postgraduate APA 7 literature review about renewable energy, final draft."
    )
    assert data["assignment_type"] == "Literature Review"
    assert data["topic"] == "renewable energy"
    assert data["word_count"] == 2000
    assert data["academic_level"] == "Postgraduate"
    assert data["citation_style"] == "APA 7"
    assert data["requested_mode"] == "final_draft"


def test_outline_only_does_not_require_a_citation_style():
    data = parse_assignment_request("Create only the essay outline first about robotics")
    assert data["requested_mode"] == "outline_only"
    assert "citation style" not in missing_essential_details(data)


def test_harvard_requires_the_institutional_variant():
    data = parse_assignment_request("Write a 1,000-word Harvard essay about robotics")
    assert "university Harvard guide or template" in missing_essential_details(data)
    updated = parse_assignment_request("Use the provided university template", data)
    assert "university Harvard guide or template" not in missing_essential_details(updated)


def test_contextual_followup_updates_existing_assignment():
    state = {"university_assignment": parse_assignment_request(
        "Write an APA essay about education"
    )}
    intent = classify_assignment_intent("Make it 3,000 words", state)
    assert intent["params"]["word_count"] == 3000
    assert intent["params"]["topic"] == "education"


def test_pending_assignment_preempts_generic_pending_route():
    ctx = SimpleNamespace(
        state={"university_assignment": parse_assignment_request(
            "Write an APA essay about education"
        )},
        pending={"kind": "university_assignment"},
        router=None,
    )
    route = select_route("Make it 3,000 words", ctx)
    assert route["route_type"] == "intent"
    assert route["intent"]["skill"] == "university.assignment"


def _source(index=1):
    return {
        "title": f"Verified Source {index}",
        "publisher": "example.edu",
        "url": f"https://example.edu/source-{index}",
        "publication_date": "2025-03-14",
        "access_time": "2026-07-23T08:00:00+0400",
        "citation_identifier": f"[{index}]",
        "notes": "Verified evidence from the fetched page.",
    }


def test_reference_format_never_invents_an_author():
    source = _source()
    reference = assignment._reference(source, 1, "APA 7")
    assert reference.startswith("example.edu. (2025).")
    assert "Unknown" not in reference
    assert source["url"] in reference


def test_citation_conversion_accepts_source_marker_spacing():
    sources = [_source(1), _source(2)]
    converted = assignment._apply_citation_style(
        "First claim [ 1 ]; second claim [2].", sources, "APA 7"
    )
    assert "[" not in converted
    assert converted.count("(example.edu, 2025)") == 2


def test_assignment_body_word_limiter_is_deterministic():
    text = " ".join(f"word{index}" for index in range(100))
    limited = assignment._limit_words(text, 35)
    assert len(limited.split()) == 35
    assert limited.endswith(".")


def test_prepare_session_rejects_fewer_than_three_verified_sources(monkeypatch):
    from skills import research

    monkeypatch.setattr(research, "save_session", lambda _session: None)
    monkeypatch.setattr(research, "gather_sources", lambda *_args, **_kwargs: [_source(1), _source(2)])
    ctx = SimpleNamespace(llm=SimpleNamespace(available=False), state={})
    data = parse_assignment_request("Write an APA essay about robotics")
    assert assignment._prepare_session(data, ctx, None) is None


class _Registry:
    def __init__(self):
        self.updates = []

    def register(self, *_args, **_kwargs):
        return {"id": "assignment-doc"}

    def update_entry(self, *args, **kwargs):
        self.updates.append((args, kwargs))


class _WordService:
    instances = []

    def __init__(self):
        self.process_id = 321
        self.window_handle = 654
        self.operations = []
        self.__class__.instances.append(self)

    def open(self, visible=True):
        assert visible is True

    def new_document(self):
        return "document"

    def insert_heading(self, text, level=1, doc=None):
        self.operations.append(("heading", text))

    def type_visibly(self, text, doc=None):
        self.operations.append(("paragraph", text))

    def save(self, path, doc=None):
        Path(path).write_bytes(b"assignment")

    def close(self, save=False):
        return None


def _context():
    return SimpleNamespace(
        state={}, pending=None, registry=_Registry(),
        live_task=LiveTaskController(),
        llm=SimpleNamespace(available=False),
        speaker=SimpleNamespace(speak=lambda *_args, **_kwargs: None),
    )


def test_live_word_assignment_uses_verified_sources_and_safe_save(monkeypatch, tmp_path):
    import skills.office_service as office_service

    _WordService.instances.clear()
    monkeypatch.setattr(office_service, "WordService", _WordService)
    sources = [_source(1), _source(2), _source(3)]
    session = {
        "outline": ["Introduction", "Conclusion"],
        "sources": sources,
        "draft": {
            "Introduction": "Evidence from the verified page [1].",
            "Conclusion": "The verified evidence supports the conclusion [2].",
        },
    }
    monkeypatch.setattr(assignment, "_prepare_session", lambda *_args: session)
    ctx = _context()
    data = parse_assignment_request(
        "Write a 600-word APA 7 essay about renewable energy live in Word"
    )

    result = assignment.create_assignment(data, ctx)

    assert "ready in Word" in result
    assert ctx.pending["kind"] == "save_document"
    assert ctx.state["university_assignment"]["source_count"] == 3
    operations = _WordService.instances[-1].operations
    assert any("(example.edu, 2025)" in text for kind, text in operations if kind == "paragraph")

    request = ctx.pending["request"]
    target = tmp_path / "short_assignment.docx"
    request.resolved_path = str(target)
    assert request.save() is True
    assert target.is_file()
    assert ctx.state["university_assignment"]["save_status"].startswith("Saved:")


def test_outline_only_opens_word_without_research(monkeypatch):
    import skills.office_service as office_service

    _WordService.instances.clear()
    monkeypatch.setattr(office_service, "WordService", _WordService)
    monkeypatch.setattr(
        assignment,
        "_prepare_session",
        lambda *_args: (_ for _ in ()).throw(AssertionError("research should not run")),
    )
    ctx = _context()
    data = parse_assignment_request("Create only the essay outline first about robotics")

    result = assignment.create_assignment(data, ctx)

    assert "ready in Word" in result
    assert ctx.pending["kind"] == "save_document"
    assert any(text == "Assignment Outline" for _, text in _WordService.instances[-1].operations)


def test_missing_detail_clarification_does_not_open_word(monkeypatch):
    import skills.office_service as office_service

    monkeypatch.setattr(
        office_service,
        "WordService",
        lambda: (_ for _ in ()).throw(AssertionError("Word opened before clarification")),
    )
    ctx = _context()
    data = parse_assignment_request("Create a case study in APA 7")

    result = assignment.create_assignment(data, ctx)

    assert "please provide the topic" in result.lower()
    assert ctx.pending["kind"] == "university_assignment"


def test_packaged_assignment_save_target_remains_inside_test_tmp():
    from config import Config
    from core.save_workflow import PendingSaveRequest

    request = PendingSaveRequest(
        task_id="packaged-test", document_type="Word",
        suggested_filename="Short Assignment", suggested_extension=".docx",
        current_application="Microsoft Word", save_callback=lambda _path: None,
    )
    target = request.resolve(".test_tmp")
    assert target.parent.resolve() == Config.TEMP_DIR.resolve()
