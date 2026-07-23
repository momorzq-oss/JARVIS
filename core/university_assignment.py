"""Shared semantic extraction for university-assignment commands and follow-ups."""
from __future__ import annotations

import re


ASSIGNMENT_TYPES = (
    ("annotated bibliography", "Annotated Bibliography"),
    ("compare-and-contrast assignment", "Compare-and-Contrast Assignment"),
    ("compare and contrast assignment", "Compare-and-Contrast Assignment"),
    ("presentation outline", "Presentation Outline"),
    ("dissertation chapter", "Dissertation Chapter"),
    ("thesis section", "Thesis Section"),
    ("literature review", "Literature Review"),
    ("reflective writing", "Reflective Writing"),
    ("business report", "Business Report"),
    ("research paper", "Research Paper"),
    ("research report", "Research Report"),
    ("project milestone", "Project Milestone"),
    ("milestone", "Project Milestone"),
    ("critical analysis", "Critical Analysis"),
    ("case study", "Case Study"),
    ("lab report", "Lab Report"),
    ("proposal", "Proposal"),
    ("dissertation", "Dissertation Chapter"),
    ("thesis", "Thesis Section"),
    ("essay", "Essay"),
    ("report", "Report"),
)

CITATION_STYLES = (
    (r"\bharvard\b", "Harvard"),
    (r"\bapa(?:\s*7(?:th)?)?\b", "APA 7"),
    (r"\bmla(?:\s*9(?:th)?)?\b", "MLA 9"),
    (r"\bchicago\b", "Chicago"),
    (r"\bieee\b", "IEEE"),
    (r"\bvancouver\b", "Vancouver"),
    (r"\boscola\b", "OSCOLA"),
)


def _assignment_type(text):
    low = text.lower()
    for marker, label in ASSIGNMENT_TYPES:
        if re.search(rf"\b{re.escape(marker)}\b", low):
            if marker == "report" and not re.search(
                r"\b(?:university|academic|assignment|student|college|citation|"
                r"harvard|apa|mla|chicago|ieee|vancouver|oscola)\b|"
                r"\b\d[\d,]*\s*(?:-| )?words?\b",
                low,
            ):
                continue
            return label
    return ""


def _citation_style(text):
    for pattern, label in CITATION_STYLES:
        if re.search(pattern, text, re.I):
            return label
    return ""


def _word_count(text):
    match = re.search(r"\b(\d{1,3}(?:,\d{3})*|\d{3,6})\s*(?:-| )?words?\b", text, re.I)
    return int(match.group(1).replace(",", "")) if match else None


def _academic_level(text):
    levels = (
        (r"\b(?:phd|doctoral|doctorate)\b", "Doctoral"),
        (r"\b(?:master'?s?|postgraduate|graduate)\b", "Postgraduate"),
        (r"\b(?:bachelor'?s?|undergraduate)\b", "Undergraduate"),
        (r"\b(?:foundation|first[- ]year)\b", "Foundation"),
    )
    for pattern, label in levels:
        if re.search(pattern, text, re.I):
            return label
    return ""


def _mode(text):
    low = text.lower()
    if re.search(r"\b(?:outline only|only the outline|outline first)\b", low):
        return "outline_only"
    if re.search(r"\b(?:references only|only (?:the )?references|bibliography only)\b", low):
        return "references_only"
    if re.search(r"\b(?:proofread|proofreading|edit|fix the references|fix .*formatting)\b", low):
        return "editing"
    if re.search(r"\bfirst draft\b", low):
        return "first_draft"
    if re.search(r"\bfinal (?:draft|version)\b", low):
        return "final_draft"
    return "live_word"


def _milestone_stage(text):
    match = re.search(
        r"\b(?:milestone|chapter|stage|section)\s+([a-z0-9-]+)\b", text, re.I
    )
    return f"{match.group(0).title()}" if match else ""


def _deadline(text):
    match = re.search(
        r"\b(?:due|deadline(?: is)?|submit by)\s+(.+?)(?=[,.!?]|$)", text, re.I
    )
    return match.group(1).strip() if match else ""


def _topic(text):
    patterns = (
        r"\b(?:about|on|regarding|concerning)\s+(.+)$",
        r"\b(?:for)\s+(?:my\s+)?(?:project|assignment)\s+(?:about|on)\s+(.+)$",
    )
    value = ""
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = match.group(1).strip()
            break
    if not value:
        return ""
    value = re.split(
        r"\b(?:using|in)\s+(?:harvard|apa|mla|chicago|ieee|vancouver|oscola)\b|"
        r"\b(?:for|at)\s+(?:undergraduate|postgraduate|master|doctoral|phd)\b|"
        r"\b(?:live|visibly)\s+in\s+(?:microsoft\s+)?word\b|"
        r"\b(?:and\s+)?save\s+(?:it\s+)?(?:to|in)\b|"
        r"\b(?:as\s+(?:an?\s+)?)?(?:outline only|first draft|final draft|final version)\b",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]
    value = re.sub(r"\b\d[\d,]*\s*(?:-| )?words?\b", "", value, flags=re.I)
    return value.strip(" ,.-")


def parse_assignment_request(text, existing=None):
    """Extract one canonical assignment state from a request or follow-up."""
    request = str(text or "").strip()
    data = dict(existing or {})
    detected_type = _assignment_type(request)
    detected_topic = _topic(request)
    detected_count = _word_count(request)
    detected_style = _citation_style(request)
    detected_level = _academic_level(request)
    detected_stage = _milestone_stage(request)
    detected_deadline = _deadline(request)
    if detected_type:
        data["assignment_type"] = detected_type
    if detected_topic:
        data["topic"] = detected_topic
    if detected_count is not None:
        data["word_count"] = detected_count
    if detected_style:
        data["citation_style"] = detected_style
    if detected_level:
        data["academic_level"] = detected_level
    if detected_stage:
        data["milestone_stage"] = detected_stage
    if detected_deadline:
        data["deadline"] = detected_deadline
    guide_match = re.search(
        r"\b(?:use|follow)\s+(.+?(?:university|college).+?harvard(?:\s+guide)?)\b|"
        r"\b(?:use|follow)\s+(?:the\s+)?(?:provided|attached|my university)\s+"
        r"(?:university\s+)?(?:template|rubric|brief|marking criteria|harvard guide)\b",
        request,
        re.I,
    )
    if guide_match:
        data["harvard_guide"] = (guide_match.group(1) or guide_match.group(0)).strip()
    if not existing or re.search(
        r"\b(?:outline|draft|version|proofread|edit|references only|bibliography only)\b",
        request,
        re.I,
    ):
        data["requested_mode"] = _mode(request)
    data.setdefault("academic_level", "Undergraduate")
    data.setdefault("requested_mode", "live_word")
    data.setdefault("word_count", None)
    data.setdefault("citation_style", "")
    data.setdefault("milestone_stage", "")
    data.setdefault("deadline", "")
    data.setdefault("current_section", "Waiting")
    data.setdefault("progress", 0)
    data.setdefault("source_count", 0)
    data.setdefault("reference_count", 0)
    data.setdefault("save_status", "Not saved")
    data["original_request"] = data.get("original_request") or request
    return data


def missing_essential_details(data):
    missing = []
    if not data.get("assignment_type"):
        missing.append("assignment type")
    if not data.get("topic"):
        missing.append("topic")
    mode = data.get("requested_mode")
    requires_sources = mode not in {"outline_only", "editing"}
    if requires_sources and not data.get("citation_style"):
        missing.append("citation style")
    if data.get("citation_style") == "Harvard" and not data.get("harvard_guide"):
        missing.append("university Harvard guide or template")
    return missing


def classify_assignment_intent(text, state=None):
    """Return the one registered assignment intent for creation and follow-ups."""
    request = str(text or "").strip()
    if not request:
        return None
    # Save/close/task controls belong to the active workflow. Words such as
    # "assignment" may legitimately appear in a requested filename and must
    # never restart University Mode while its Word document is awaiting save.
    if re.match(r"^(?:save|close|pause|resume|cancel|stop)\b", request, re.I):
        return None
    current = state.get("university_assignment") if isinstance(state, dict) else None
    detected_type = _assignment_type(request)
    strong_type = bool(detected_type)
    # Academic words inside the subject do not make an ordinary Office file
    # an assignment. Keep directive evidence such as "university proposal"
    # or "using APA", but exclude the extracted topic before checking mode.
    signal_request = request
    detected_topic = _topic(request)
    if detected_topic:
        signal_request = re.sub(
            re.escape(detected_topic), " ", signal_request,
            count=1, flags=re.I,
        )
    academic_signal = bool(re.search(
        r"\b(?:university|academic|assignment|rubric|marking criteria|citation|"
        r"harvard|apa|mla|chicago|ieee|vancouver|oscola)\b",
        signal_request, re.I,
    ))
    followup = bool(current and re.search(
        r"\b(?:make it|use harvard|use apa|add more sources|rewrite the|continue with|"
        r"references|formatting|outline|first draft|final version|word count)\b",
        request,
        re.I,
    ))
    # These phrases already power JARVIS's general research/report workflow.
    # Enter University Mode only when the user supplies academic evidence;
    # otherwise preserve the verified legacy route exactly.
    overlapping_general_types = {
        "Report", "Research Report", "Research Paper", "Literature Review",
        "Business Report", "Critical Analysis", "Case Study", "Proposal",
    }
    if detected_type in overlapping_general_types and not academic_signal and not followup:
        return None
    if not (strong_type or academic_signal or followup):
        return None
    parsed = parse_assignment_request(request, current if followup else None)
    return {"skill": "university.assignment", "params": parsed}
