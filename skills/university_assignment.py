"""Source-grounded, progressively visible University Assignment Mode."""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from config import Config
from core.live_task import LIVE_INTERACTIVE, TaskCancelled
from core.save_workflow import PendingSaveRequest
from core.university_assignment import missing_essential_details, parse_assignment_request


STRUCTURES = {
    "Essay": ("Introduction", "Main Arguments", "Counterargument", "Conclusion"),
    "Research Paper": ("Abstract", "Introduction", "Methodology", "Findings", "Discussion", "Limitations", "Conclusion"),
    "Research Report": ("Executive Summary", "Introduction", "Aims and Objectives", "Methodology", "Findings", "Discussion", "Limitations", "Conclusion", "Recommendations"),
    "Report": ("Executive Summary", "Introduction", "Analysis", "Findings", "Conclusion", "Recommendations"),
    "Literature Review": ("Introduction", "Scope and Search Method", "Thematic Review", "Critical Comparison", "Research Gaps", "Conclusion"),
    "Case Study": ("Background", "Problem", "Analysis", "Application of Theory", "Options", "Recommendation", "Conclusion"),
    "Lab Report": ("Abstract", "Introduction", "Method", "Results", "Discussion", "Conclusion"),
    "Business Report": ("Executive Summary", "Introduction", "Analysis", "Findings", "Recommendations", "Conclusion"),
    "Project Milestone": ("Project Status", "Completed Work", "Current Work", "Evidence", "Risks and Issues", "Next Actions", "Timeline", "Deliverables"),
    "Proposal": ("Introduction", "Problem Statement", "Aims and Objectives", "Proposed Methodology", "Timeline", "Expected Outcomes", "Conclusion"),
    "Dissertation Chapter": ("Introduction", "Literature Review", "Methodology", "Findings", "Discussion", "Conclusion"),
    "Thesis Section": ("Introduction", "Literature Review", "Methodology", "Findings", "Discussion", "Conclusion"),
    "Reflective Writing": ("Introduction", "Experience", "Critical Reflection", "Learning", "Action Plan", "Conclusion"),
    "Annotated Bibliography": ("Scope", "Search Method", "Annotated Sources", "Synthesis", "Conclusion"),
    "Critical Analysis": ("Introduction", "Context", "Critical Evaluation", "Alternative Perspectives", "Conclusion"),
    "Compare-and-Contrast Assignment": ("Introduction", "Comparison Criteria", "Similarities", "Differences", "Critical Evaluation", "Conclusion"),
    "Presentation Outline": ("Purpose", "Key Message", "Slide Outline", "Evidence", "Conclusion"),
}


def _clarification(data):
    missing = missing_essential_details(data)
    if not missing:
        return ""
    if len(missing) == 1:
        wanted = missing[0]
    else:
        wanted = ", ".join(missing[:-1]) + f", and {missing[-1]}"
    return f"Before I create the assignment, please provide the {wanted}."


def _outline(data):
    return list(STRUCTURES.get(data.get("assignment_type"), STRUCTURES["Report"]))


def _source_author(source):
    return str(source.get("author") or source.get("publisher") or "").strip()


def _source_year(source):
    date = str(source.get("publication_date") or "")
    match = re.search(r"\b(?:19|20)\d{2}\b", date)
    return match.group(0) if match else "n.d."


def _inline_citation(source, index, style):
    author = _source_author(source)
    year = _source_year(source)
    if style in {"Harvard", "APA 7"}:
        return f"({author or source.get('title', 'Source')}, {year})"
    if style == "MLA 9":
        return f"({author or source.get('title', 'Source')})"
    return f"[{index}]"


def _apply_citation_style(text, sources, style):
    value = str(text or "")
    for index, source in enumerate(sources, 1):
        value = re.sub(
            rf"\[\s*{index}\s*\]",
            lambda _match, item=source, number=index: _inline_citation(
                item, number, style
            ),
            value,
        )
    return value


def _limit_words(text, maximum):
    """Bound body prose without inventing filler or altering its source text."""
    raw = str(text or "")
    words = raw.split()
    limit = max(1, int(maximum))
    if len(words) <= limit:
        return " ".join(words)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", raw) if part.strip()]
    if len(paragraphs) <= 1:
        value = " ".join(words[:limit]).rstrip(" ,;:-")
        return value if value.endswith((".", "!", "?")) else value + "."

    remaining = limit
    bounded = []
    for index, paragraph in enumerate(paragraphs):
        parts = paragraph.split()
        paragraphs_left = len(paragraphs) - index
        allowance = max(1, remaining // paragraphs_left)
        selected = parts[:allowance]
        marker = re.search(r"\[\s*\d+\s*\]\s*$", paragraph)
        if marker and not re.search(r"\[\s*\d+\s*\]", " ".join(selected)):
            if len(selected) >= allowance:
                selected[-1] = marker.group(0)
            else:
                selected.append(marker.group(0))
        value = " ".join(selected).rstrip(" ,;:-")
        if value and value[-1] not in ".!?]":
            value += "."
        bounded.append(value)
        remaining -= len(selected)
    return "\n\n".join(bounded)


def _reference(source, index, style):
    author = _source_author(source)
    title = str(source.get("title") or "Untitled source").strip()
    publisher = str(source.get("publisher") or "").strip()
    url = str(source.get("url") or "").strip()
    year = _source_year(source)
    accessed = str(source.get("access_time") or "").split("T", 1)[0]
    lead = author or title
    if style == "Harvard":
        return f"{lead} ({year}) '{title}', {publisher}. Available at: {url} (Accessed: {accessed})."
    if style == "APA 7":
        return f"{lead}. ({year}). {title}. {publisher}. {url}"
    if style == "MLA 9":
        return f'{lead}. "{title}." {publisher}, {year}, {url}. Accessed {accessed}.'
    if style == "Chicago":
        return f'{lead}. "{title}." {publisher}. Accessed {accessed}. {url}.'
    if style == "OSCOLA":
        return f"{lead}, '{title}' ({publisher}, {year}) <{url}> accessed {accessed}."
    return f"[{index}] {lead}. {title}. {publisher}, {year}. {url}."


def _set_state(ctx, data, **changes):
    data.update(changes)
    ctx.state["university_assignment"] = dict(data)


def _prepare_session(data, ctx, task):
    from skills import research

    session = research._blank_session(data["topic"])
    session["outline"] = _outline(data)
    research.save_session(session)
    sources = research.gather_sources(
        session,
        ctx,
        max_sources=max(3, min(10, int(data.get("source_target") or 6))),
        progress_cb=lambda step: _progress(ctx, data, task, step, 20),
        checkpoint=task.checkpoint if task is not None else None,
        summarize_with_llm=True,
    )
    if len(sources) < 3:
        return None
    target = int(data.get("word_count") or 1200)
    words_per_section = max(60, target // max(1, len(session["outline"])))
    session["draft"] = {}
    for index, section in enumerate(session["outline"], 1):
        if task is not None:
            task.checkpoint()
        _progress(
            ctx, data, task,
            f"Drafting {section}",
            30 + int(index * 30 / max(1, len(session["outline"]))),
            current_section=section,
        )
        session["draft"][section] = _limit_words(
            research.draft_section(
                session,
                section,
                ctx,
                extra=(
                    f"Write approximately {words_per_section} words at "
                    f"{data.get('academic_level')} level. Use only supplied sources."
                ),
            ),
            words_per_section,
        )
    session["stage"] = "DONE"
    research.save_session(session)
    return session


def _progress(ctx, data, task, step, progress, **metadata):
    _set_state(ctx, data, current_section=metadata.get("current_section", step), progress=progress)
    if task is not None:
        task.update(step=step, progress=progress, **metadata)


def create_assignment(data, ctx):
    """Create one validated assignment progressively in a JARVIS-owned Word document."""
    data = parse_assignment_request(data.get("original_request", ""), data)
    clarification = _clarification(data)
    _set_state(ctx, data)
    if clarification:
        ctx.pending = {"kind": "university_assignment", "assignment": data}
        return clarification

    task = getattr(ctx, "live_task", None)
    task_id = uuid.uuid4().hex[:12]
    if task is not None:
        task.start(
            task_id,
            f"{data['assignment_type']}: {data['topic']}",
            application="Microsoft Word",
            mode=LIVE_INTERACTIVE,
        )
        task.state.delay_ms = max(0, Config.LIVE_TYPING_DELAY_MS)

    try:
        outline_only = data.get("requested_mode") == "outline_only"
        session = {"outline": _outline(data), "sources": [], "draft": {}}
        if not outline_only:
            session = _prepare_session(data, ctx, task)
            if session is None:
                if task is not None:
                    task.fail("Fewer than three verified sources")
                _set_state(ctx, data, save_status="Failed: insufficient verified sources")
                return "I could not verify at least three real sources, so I did not create a referenced assignment."

        sources = list(session.get("sources") or [])
        _set_state(
            ctx, data, source_count=len(sources), reference_count=len(sources),
            current_section="Opening Microsoft Word", progress=62,
        )
        if task is not None:
            task.update(
                step="Opening Microsoft Word", progress=62,
                sources_found=len(sources), sources_verified=len(sources),
                citation_count=len(sources), assignment=dict(data),
            )

        from skills.office_service import WordService

        service = WordService()
        service.open(visible=True)
        document = service.new_document()
        entry = ctx.registry.register(
            "document",
            f"{data['topic'].title()} {data['assignment_type']}",
            window_title="Word",
            pid=service.process_id,
            hwnd=service.window_handle,
            closer=lambda svc=service: svc.close(save=False),
            extra={
                "unsaved": "true", "owner": "jarvis",
                "application": "Microsoft Word", "process_name": "WINWORD.EXE",
                "assignment_type": data["assignment_type"],
            },
        )

        operations = [("title", data["topic"].title())]
        if data.get("milestone_stage"):
            operations.append(("paragraph", data["milestone_stage"]))
        if outline_only:
            operations.append(("heading", "Assignment Outline"))
            operations.extend(("heading", section) for section in session["outline"])
        elif data.get("requested_mode") == "references_only":
            operations.append(("heading", "References"))
        else:
            for section in session["outline"]:
                operations.append(("heading", section))
                content = _apply_citation_style(
                    session.get("draft", {}).get(section, ""),
                    sources,
                    data["citation_style"],
                )
                for paragraph in re.split(r"\n\s*\n", content):
                    if paragraph.strip():
                        operations.append(("paragraph", paragraph.strip()))
            operations.append(("heading", "References"))
        if not outline_only:
            for index, source in enumerate(sources, 1):
                operations.append(("paragraph", _reference(source, index, data["citation_style"])))

        total = max(1, len(operations))
        for index, (kind, value) in enumerate(operations, 1):
            if task is not None:
                task.checkpoint()
            progress = 62 + int(index * 37 / total)
            _progress(
                ctx, data, task, value[:100], progress,
                current_section=value[:100],
                source_count=len(sources), reference_count=len(sources),
            )
            if kind in {"title", "heading"}:
                service.insert_heading(value, level=1, doc=document)
            else:
                service.type_visibly(value, doc=document)
            if task is not None and task.state.delay_ms:
                time.sleep(task.state.delay_ms / 1000.0)

        def save(path, svc=service, doc=document, entry_id=entry["id"]):
            svc.save(path, doc=doc)
            if not Path(path).is_file():
                raise RuntimeError("Word save did not create the requested file")
            ctx.registry.update_entry(
                entry_id,
                name=Path(path).name,
                display_name=Path(path).name,
                window_title=Path(path).stem,
                file_path=str(path),
                unsaved_state="saved",
            )
            _set_state(ctx, data, save_status=f"Saved: {path}", progress=100)

        request = PendingSaveRequest(
            task_id=task_id,
            document_type="Word",
            suggested_filename=f"{data['topic'].title()} {data['assignment_type']}",
            suggested_extension=".docx",
            current_application="Microsoft Word",
            save_callback=save,
        )
        ctx.pending = {"kind": "save_document", "request": request}
        ctx.state["word_service"] = service
        ctx.state["active_office_entry"] = entry["id"]
        _set_state(ctx, data, current_section="Complete", progress=100, save_status="Awaiting save location")
        if task is not None:
            task.complete()
        return "The assignment is ready in Word. Where would you like me to save it?"
    except TaskCancelled:
        _set_state(ctx, data, save_status="Cancelled")
        return "The university assignment task was cancelled."
    except Exception as exc:
        if task is not None:
            task.fail(exc)
        _set_state(ctx, data, save_status=f"Failed: {exc}")
        return f"The university assignment task failed: {exc}."


def handle_followup(text, ctx):
    current = dict(ctx.state.get("university_assignment") or {})
    data = parse_assignment_request(text, current)
    ctx.pending = None
    return create_assignment(data, ctx)


def handle(intent, ctx):
    params = dict(intent.get("params") or {})
    return create_assignment(params, ctx)
