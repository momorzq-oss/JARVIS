"""Deterministic natural-language intents for desktop and web automation."""
from __future__ import annotations

import re


APPLICATION_ALIASES = {
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "outlook": "Microsoft Outlook",
    "onenote": "Microsoft OneNote",
    "access": "Microsoft Access",
    "teams": "Microsoft Teams",
    "paint": "Microsoft Paint",
    "edge": "Microsoft Edge",
    "chrome": "Google Chrome",
    "notepad": "Notepad",
    "calculator": "Calculator",
    "file explorer": "File Explorer",
    "explorer": "File Explorer",
}

FOLDER_ALIASES = {
    "desktop": "Desktop",
    "downloads": "Downloads",
    "documents": "Documents",
    "pictures": "Pictures",
    "videos": "Videos",
    "music": "Music",
    "onedrive": "OneDrive",
    "home": "Home",
    "this pc": "This PC",
    "recycle bin": "Recycle Bin",
    "network": "Network",
}

SITE_ALIASES = {
    "google": "google",
    "youtube": "youtube",
    "gmail": "gmail",
    "google drive": "google drive",
    "drive": "google drive",
    "google docs": "google docs",
    "docs": "google docs",
    "google sheets": "google sheets",
    "sheets": "google sheets",
    "google slides": "google slides",
    "slides": "google slides",
    "stripe": "stripe",
    "github": "github",
    "microsoft 365": "microsoft 365",
    "office 365": "microsoft 365",
    "linkedin": "linkedin",
    "tiktok": "tiktok",
    "instagram": "instagram",
    "facebook": "facebook",
    "x": "x",
    "twitter": "x",
}

# Keep browser wording local and deliberately small.  These are destination
# aliases, not a cloud classifier vocabulary: the parser below still extracts
# a free-form topic from the rest of the request.
BROWSER_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "google browser": "chrome",
    # Common speech-recognition substitution when the speaker asks to browse.
    "chromecast browser": "chrome",
    "browser": "chrome",
    "a browser": "chrome",
    "web browser": "chrome",
}

_BROWSER_FILLER = re.compile(
    r"\b(?:please|for me|can you|could you|would you|i want to|i need to|"
    r"can you get|let me|something|a good|the best|most relevant|useful|"
    r"information|me|about|on|for|to|of|with|explaining|explain|"
    r"that teaches|which teaches|teaching|teaches|show me|look up)\b",
    re.I,
)
_BROWSER_STOP_WORDS = {
    "a", "an", "and", "about", "for", "how", "i", "in", "is", "it",
    "me", "my", "of", "on", "or", "please", "the", "this", "to", "with",
}

_BROWSER_RESULT_SELECTION_SUFFIX = re.compile(
    r"(?:^|\s+)(?:(?:and|then)\s+)?(?:please\s+)?"
    r"(?:(?:play|open|start|watch|choose|select)\s+)?(?:the\s+)?"
    r"(?:(?:first|top|best|good|relevant|matching|most\s+relevant|most\s+useful)\s+)+"
    r"(?:result|video|one)(?:\s+for\s+me)?[\s.!?,;:]*$",
    re.I,
)


def _clean_browser_query(value):
    """Remove request scaffolding while leaving the user topic untouched."""
    query = str(value or "").strip(" .,!?:;-\t\r\n")
    query = re.sub(
        r"^(?:and|then|for|about|on|regarding|of)\s+", "", query, flags=re.I,
    )
    query = re.sub(r"^(?:a|an)\s+", "", query, flags=re.I)
    query = re.sub(
        r"\b(?:on|in)\s+(?:the\s+)?(?:web|google|youtube)\b", "", query,
        flags=re.I,
    )
    query = re.sub(r"\s+", " ", query).strip(" .,!?:;-")
    return query


def _query_terms(query):
    return {
        word for word in re.findall(r"[a-z0-9]+", str(query).lower())
        if len(word) > 1 and word not in _BROWSER_STOP_WORDS
    }


def _browser_context(state):
    """Read only the compact, non-sensitive context kept by web automation."""
    if not isinstance(state, dict):
        return {}
    context = state.get("browser_context", {})
    return context if isinstance(context, dict) else {}


def _browser_params(*, destination="", query="", content_type="web_page",
                    action="open", browser="", new_tab=False, selection="",
                    target="", site=""):
    """Build one inspectable local browser action without empty noise."""
    params = {"intent_group": "BROWSER_LOCAL", "action": action}
    if destination:
        params["destination"] = destination
    if query:
        params["query"] = query
    if content_type:
        params["content_type"] = content_type
    if browser:
        params["browser"] = browser
    if new_tab:
        params["new_tab"] = True
    if selection:
        params["selection"] = selection
    if target:
        params["target"] = target
    if site:
        params["site"] = site
    return params


def _extract_browser_query(cleaned, destination=""):
    """Extract a topic from flexible search/video phrasing without an LLM."""
    value = cleaned
    # Strip a destination whether it appears at the beginning or after a verb.
    if destination == "youtube":
        value = re.sub(r"\b(?:on\s+)?youtube\b", " ", value, flags=re.I)
    elif destination == "google":
        value = re.sub(r"\b(?:on\s+)?google\b", " ", value, flags=re.I)

    marker = re.search(
        r"\b(?:search|find|look for|look up|show me|show|play|watch)\s*"
        r"(?:for\s+)?(.+)$",
        value, re.I,
    )
    if marker:
        value = marker.group(1)

    # Result selection describes what to do with search results, not what to
    # search for.  Remove it once here so every Google/YouTube phrasing shares
    # the same topic extractor (including speech variants such as "open the
    # best one" and "play the first good result").
    value = _BROWSER_RESULT_SELECTION_SUFFIX.sub("", value)

    value = re.sub(
        r"\b(?:open|launch|bring up|go to|navigate to|search|find|look|look for|"
        r"look up|show|play|watch|browse|searching)\b", " ", value, flags=re.I,
    )
    value = re.sub(
        r"\b(?:a|an|the)?\s*(?:educational\s+)?(?:video|videos|tutorial|"
        r"tutorials|lesson|lessons|article|articles|documentation|docs?|web page)\b",
        " ", value, flags=re.I,
    )
    value = _BROWSER_FILLER.sub(" ", value)
    return _clean_browser_query(value)


def classify_browser_intent(text, state=None):
    """Classify ordinary browser requests without a model or cloud service.

    The result is deliberately a normal JARVIS intent.  Execution remains in
    the existing action schema and BrowserAutomationService; this function
    only turns flexible language into structured, reviewable parameters.
    """
    cleaned = normalize_automation_text(text)
    low = cleaned.lower().strip(" .!?")
    if not low:
        return None

    # Retain the compact established intents for exact legacy commands; the
    # fast lane below already handles them locally.  This keeps compatibility
    # for callers that compare those small payloads exactly.
    if re.fullmatch(r"open (?:the )?(?:web )?browser", low):
        return None
    if re.fullmatch(r"search google(?: for)? .+", low):
        return None
    if re.match(r"(?:find|locate|search for) (?:the )?file\b", low):
        return None
    if re.fullmatch(r"play (?:the )?first (?:result|video)", low):
        return None

    context = _browser_context(state)
    active_destination = str(context.get("destination") or "").lower()
    previous_query = str(context.get("query") or "").strip()
    new_tab = bool(re.search(r"\b(?:open|start|make)\s+(?:a\s+)?new tab\b|\bin a new tab\b", low))
    explicit_youtube = bool(re.search(r"\byoutube\b", low))
    explicit_google = bool(re.search(r"\bgoogle\b", low))
    browser_name = next(
        (name for name in sorted(BROWSER_ALIASES, key=len, reverse=True)
         if re.search(rf"\b{re.escape(name)}\b", low)),
        "",
    )
    browser = BROWSER_ALIASES.get(browser_name, "")

    if re.fullmatch(r"(?:go online|browse the web|i need to browse(?: the web)?)", low):
        return {"skill": "browser.open", "params": _browser_params(
            destination="browser", action="open", browser="chrome",
        )}

    # Music is intentionally handled by the established media service.  A
    # bare "play <title> on YouTube" is music unless the speaker identifies
    # educational/video content or a result-selection request.
    if re.search(r"\b(?:music|song|track|album|artist)\b", low):
        return None
    if (low.startswith("play ") and explicit_youtube
            and not re.search(r"\b(?:video|tutorial|lesson|educational|documentary)\b", low)
            and not re.search(r"\b(?:best|most relevant|useful)\b", low)):
        return None

    # Tab and playback controls must win over broad "close" or "play" rules.
    if re.fullmatch(r"(?:open )?(?:this |that )?(?:in )?(?:a )?new tab", low):
        return {"skill": "browser.new_tab", "params": _browser_params(
            destination=active_destination, action="new_tab", browser=browser,
            new_tab=True,
        )}
    if re.fullmatch(r"(?:close|shut) (?:this |the |current |last )?tab", low):
        return {"skill": "browser.close_tab", "params": _browser_params(
            destination=active_destination, action="close_tab", target="current",
        )}
    named_tab = re.fullmatch(r"(?:close|shut) (?:the )?(youtube|google) tab", low)
    if named_tab:
        return {"skill": "browser.close_tab", "params": _browser_params(
            destination=named_tab.group(1), action="close_tab", target=named_tab.group(1),
        )}
    if active_destination == "youtube" and re.fullmatch(r"(?:pause|resume|continue|play|mute|unmute)(?: it| this| the video)?", low):
        action = low.split()[0]
        if action in {"pause", "resume", "continue"}:
            return {"skill": "browser.pause_video" if action == "pause" else "browser.play_video",
                    "params": _browser_params(destination="youtube", action=action)}
        if action == "play":
            return {"skill": "browser.play_video", "params": _browser_params(destination="youtube", action=action)}

    if re.fullmatch(r"(?:go|navigate) back|back to the previous page", low):
        return {"skill": "browser.back", "params": _browser_params(
            destination=active_destination, action="back",
        )}
    if re.fullmatch(r"(?:go|navigate) forward", low):
        return {"skill": "browser.forward", "params": _browser_params(
            destination=active_destination, action="forward",
        )}

    site_names = "|".join(sorted((re.escape(name) for name in SITE_ALIASES), key=len, reverse=True))
    site_match = re.fullmatch(rf"(?:open|go to|show|launch|bring up) (?:the )?({site_names})", low)
    if site_match:
        site = SITE_ALIASES[site_match.group(1)]
        return {"skill": "browser.open_site", "params": _browser_params(
            destination=site, action="open", browser=browser, new_tab=new_tab,
            target=site, site=site,
        )}

    # Browser/window close is intentionally distinct from closing a YouTube
    # or Google tab.  The latter only affects JARVIS-owned browser pages.
    if re.fullmatch(r"(?:close|exit|quit|shut down|shut) (?:the )?(?:browser|chrome|google chrome|google browser|chromecast browser)", low):
        return {"skill": "browser.close", "params": _browser_params(
            destination="browser", action="close", browser=browser or "chrome", target="browser",
        )}
    if re.fullmatch(r"(?:close|exit|quit|shut) (?:the )?(youtube|google)", low):
        target = re.fullmatch(r"(?:close|exit|quit|shut) (?:the )?(youtube|google)", low).group(1)
        return {"skill": "browser.close_tab", "params": _browser_params(
            destination=target, action="close_tab", target=target,
        )}
    if low in {"close it", "close this", "close that"} and active_destination in {"youtube", "google"}:
        return {"skill": "browser.close_tab", "params": _browser_params(
            destination=active_destination, action="close_tab", target="current",
        )}

    # A search/play request can name a site, name a media type, or use the
    # active JARVIS browser context established by the previous request.
    media_video = bool(re.search(r"\b(?:video|videos|watch|watching)\b", low))
    media_tutorial = bool(re.search(r"\b(?:tutorial|tutorials|lesson|lessons)\b", low))
    asks_playback = bool(re.search(r"\b(?:play|watch)\b", low))
    asks_search = bool(re.search(r"\b(?:search|find|look for|look up|show me|browse)\b", low))
    selection = "most_relevant" if re.search(r"\b(?:best|most relevant|useful)\b", low) else ""
    if re.search(
        r"\b(?:open|start|choose|select)\s+(?:the\s+)?"
        r"(?:first|top|best|good|relevant|matching|most\s+relevant|most\s+useful)\b",
        low,
    ):
        asks_playback = True
    destination = "youtube" if explicit_youtube else "google" if explicit_google else ""
    if not destination and (media_video or asks_playback or (media_tutorial and selection)):
        destination = "youtube"
    if not destination and active_destination in {"youtube", "google"} and (asks_search or asks_playback):
        destination = active_destination
    if not destination and asks_search:
        destination = "google"

    query = _extract_browser_query(cleaned, destination)
    if query.lower() in {"one", "it", "this", "that", "another"}:
        query = ""
    if not query and previous_query and re.search(r"\b(?:one|it|this|that|another)\b", low):
        query = previous_query
    content_type = (
        "video" if media_video else "tutorial" if media_tutorial else
        "article" if re.search(r"\b(?:article|information|documentation|docs?)\b", low) else "web_page"
    )

    if destination and query and (asks_search or asks_playback or explicit_youtube or explicit_google):
        if destination == "youtube" and asks_playback:
            return {"skill": "browser.search_youtube_and_play", "params": _browser_params(
                destination="youtube", query=query, content_type=content_type,
                action="play", browser=browser, new_tab=new_tab,
                selection=selection or "most_relevant",
            )}
        return {"skill": "browser.search_youtube" if destination == "youtube" else "web.search",
                "params": _browser_params(
                    destination=destination, query=query, content_type=content_type,
                    action="search", browser=browser, new_tab=new_tab, selection=selection,
                )}

    # "Open Google and look up X" and "Open YouTube" without a query.
    if destination in {"google", "youtube"} and not query:
        return {"skill": "browser.open_site", "params": _browser_params(
            destination=destination, action="open", browser=browser, new_tab=new_tab,
            target=destination, site=destination,
        )}
    if browser or re.fullmatch(r"(?:go online|browse the web|i need to browse(?: the web)?|open (?:a |the )?(?:web )?browser)", low):
        return {"skill": "browser.open", "params": _browser_params(
            destination="browser", action="open", browser=browser or "chrome",
        )}
    return None

NUMBER_WORDS = {
    "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

DOCUMENT_TYPES = (
    "formal letter", "complaint letter", "request letter", "cover letter",
    "recommendation letter", "resignation letter", "warning letter",
    "appreciation letter", "business proposal", "project proposal",
    "research proposal", "funding proposal", "sales proposal",
    "partnership proposal", "research paper", "research report",
    "literature review", "case study", "executive brief", "policy brief",
    "meeting minutes", "business report", "progress report",
    "incident report", "technical report", "standard operating procedure",
    "contract draft", "memorandum", "press release", "personal statement",
    "curriculum vitae", "job description", "training manual",
    "questionnaire", "checklist", "proposal", "letter", "report",
    "essay", "assignment", "agenda", "survey", "document",
)


def normalize_automation_text(text):
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    replacements = (
        (r"\bmicrosoft world\b", "Microsoft Word"),
        (r"\bpower\s*point\b", "PowerPoint"),
        (r"\bexcell\b", "Excel"),
        (r"\bgoogle doc\b", "Google Docs"),
        (r"\bgoogle sheet\b", "Google Sheets"),
        (r"\bgoogle slide\b", "Google Slides"),
    )
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.I)
    return cleaned.strip(" \t\r\n")


def _intent(skill, intent_group, **params):
    return {"skill": skill, "params": {"intent_group": intent_group, **params}}


def _mode(text):
    low = text.lower()
    if any(term in low for term in ("visibly", "live", "watch you type", "type it")):
        return "structured" if any(term in low for term in ("section", "structured", "research", "proposal", "report")) else "visible"
    return "instant"


def _extract_topic(text, markers):
    for marker in markers:
        match = re.search(marker + r"\s+(.+?)[.!?]*$", text, re.I)
        if match:
            topic = match.group(1).strip(" .")
            topic = re.sub(
                r"\s+(?:in|using|with)\s+(?:microsoft\s+)?"
                r"(?:word|excel|power\s*point)\s*$",
                "", topic, flags=re.I,
            )
            return topic.strip(" .")
    return ""


def _document_type(text):
    low = text.lower()
    return next((kind for kind in DOCUMENT_TYPES if kind in low), "document")


def _strip_request_scaffolding(text):
    """Remove politeness without changing the command's entities."""
    value = str(text or "").strip()
    value = re.sub(
        r"^(?:(?:hey|okay)\s+jarvis[, ]*|jarvis[, ]*)?"
        r"(?:(?:please|kindly)\s+|(?:can|could|would|will)\s+you\s+|"
        r"i(?:'d| would)?\s+like\s+you\s+to\s+|i\s+(?:need|want)\s+(?:you\s+)?to\s+)*",
        "", value, flags=re.I,
    )
    value = re.sub(r"\s+(?:please|for me)\s*$", "", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def _extract_explicit_windows_path(text):
    """Return a literal drive or UNC path embedded in command prose.

    A path is more specific than aliases contained inside it (such as
    ``OneDrive``). Existence and target-type validation still belongs to the
    Windows resolver at execution time.
    """
    value = str(text or "").strip()
    quoted = re.search(
        r"[\"']((?:[A-Za-z]:\\|\\\\)[^\"']+)[\"']", value,
    )
    if quoted:
        return quoted.group(1).strip()
    unquoted = re.search(r"(?<![A-Za-z0-9_])((?:[A-Za-z]:\\|\\\\).+)$", value)
    if not unquoted:
        return ""
    path = unquoted.group(1).strip()
    path = re.sub(r"\s+(?:please|for me)\s*$", "", path, flags=re.I)
    return path.rstrip(" .!?;,\t\r\n")


def _research_topic(text, state=None):
    """Extract a research subject while excluding output/mode instructions."""
    value = str(text or "").strip()
    patterns = (
        r"\b(?:about|regarding|concerning)\s+(.+)$",
        r"\blook\s+into\s+(.+)$",
        r"\binvestigate\s+(.+)$",
        r"\bresearch\s+(?!report\b|paper\b|document\b)(.+)$",
        r"\bstudy\s+(?:of\s+)?(.+)$",
        r"\banalysis\s+of\s+(.+)$",
    )
    topic = ""
    for pattern in patterns:
        match = re.search(pattern, value, re.I)
        if match:
            topic = match.group(1)
            break
    if not topic:
        marker = re.search(r"\b(?:about|on)\s+(.+)$", value, re.I)
        if marker:
            topic = marker.group(1)
    topic = re.split(
        r"\s+(?:and|then)\s+(?:(?:open|create|make|write|prepare|produce|"
        r"save|type|put)\b|(?:turn|format)\s+it\b)",
        topic, maxsplit=1, flags=re.I,
    )[0]
    topic = re.split(
        r"[.!?]+\s*(?=(?:type|write|create|open|save|show|let|do)\b)",
        topic, maxsplit=1, flags=re.I,
    )[0]
    topic = re.sub(
        r"[.!?]*\s*(?:in|using)\s+(?:microsoft\s+)?word\b.*$", "", topic,
        flags=re.I,
    )
    topic = re.sub(
        r"[.!?]*\s*(?:live|visibly|so\s+i\s+can\s+watch|while\s+i\s+watch|"
        r"in\s+front\s+of\s+me)\b.*$", "", topic, flags=re.I,
    ).strip(" .,!?:;-\t\r\n")
    if topic.lower() in {"this", "that", "it", "this topic", "that topic"}:
        context = state.get("command_context", {}) if isinstance(state, dict) else {}
        topic = str(context.get("current_research_topic") or "")
    return topic


def _classify_office_creation(request):
    """Classify Office creation once for typed, voice, and fallback routing."""
    value = str(request or "").strip()
    low = value.lower().strip(" .!?")
    creation = any(
        verb in low for verb in ("create", "write", "prepare", "make", "draft", "build", "put together")
    )
    if not creation:
        return None
    if any(noun in low for noun in ("spreadsheet", "workbook", "budget", "tracker", "expense sheet")):
        topic = _extract_topic(value, (r"\b(?:about|for|on)\b",))
        if not topic:
            topic = re.sub(
                r"^(?:create|make|build|prepare) (?:a |an )?", "", value,
                flags=re.I,
            )
            topic = re.sub(
                r"\s+in (?:microsoft )?excel[.!?]*$", "", topic, flags=re.I,
            ).strip(" .")
        return _intent(
            "office.create_spreadsheet", "CREATE_SPREADSHEET", topic=topic,
            mode=_mode(value), save_after_completion=True,
        )
    if any(noun in low for noun in ("presentation", "slides", "slide deck", "pitch deck")):
        topic = _extract_topic(value, (r"\b(?:about|for|on)\b",)) or "Presentation"
        slide_match = re.search(
            r"\b(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")[- ]slide", low,
        )
        slide_count = 10
        if slide_match:
            slide_count = (
                int(slide_match.group(1)) if slide_match.group(1).isdigit()
                else NUMBER_WORDS[slide_match.group(1)]
            )
        return _intent(
            "office.create_presentation", "CREATE_PRESENTATION", topic=topic,
            slides=slide_count, mode=_mode(value), save_after_completion=True,
        )
    if any(kind in low for kind in DOCUMENT_TYPES):
        if re.search(r"\b(?:microsoft\s+)?word\b", low):
            return None
        return _intent(
            "office.create_document", "CREATE_DOCUMENT",
            document_type=_document_type(value),
            topic=_extract_topic(value, (r"\b(?:about|for|on)\b",)),
            mode=_mode(value), save_after_completion=True,
        )
    return None


def classify_local_intent(text, state=None):
    """Route flexible local commands by semantic category and precedence.

    This is deliberately shared by typed and voice input.  It handles broad
    aliases and entities; the legacy fast-lane rules remain as compatibility
    fallbacks for compact exact commands.
    """
    cleaned = normalize_automation_text(text)
    direct = cleaned.lower().strip(" .!?")
    if re.fullmatch(r"jarvis[, ]+stop", direct):
        return {"skill": "system.stop_speech", "params": {}}
    request = _strip_request_scaffolding(cleaned)
    low = request.lower().strip(" .!?")
    if not low:
        return None

    # University work has one semantic extractor and one registered execution
    # route. It precedes generic report/research rules so citation style, word
    # count, academic level and contextual follow-ups are never discarded.
    try:
        from core.university_assignment import classify_assignment_intent
        assignment = classify_assignment_intent(request, state)
        if assignment is not None:
            return assignment
    except Exception:
        pass

    # Global controls must never be swallowed by a pending workflow.
    if re.fullmatch(r"(?:emergency stop|stop everything|stop all (?:actions|automation))", low):
        return {"skill": "system.emergency_stop", "params": {}}
    if re.fullmatch(r"(?:stop speaking|kill voice|stop talking|be quiet|silence)", low):
        return {"skill": "system.stop_speech", "params": {}}
    if re.fullmatch(r"pause(?: (?:typing|the task|the current task))?", low):
        return {"skill": "task.pause", "params": {}}
    if re.fullmatch(r"(?:resume|continue)(?: (?:typing|the task|the current task))?", low):
        return {"skill": "task.resume", "params": {}}
    if re.fullmatch(r"(?:cancel|stop)(?: (?:typing|the task|the current task))?", low):
        return {"skill": "task.cancel", "params": {}}

    context = state.get("command_context", {}) if isinstance(state, dict) else {}

    # Window pronouns resolve through the same compact command context used by
    # close and Office follow-ups.  Legacy regexes otherwise pass literal
    # targets such as "it" or "current window" to the window scanner.
    active_application = str(context.get("current_application") or "").strip()
    if active_application:
        relative_target = (
            r"(?:it|this|that|this window|that window|the window|"
            r"current window|the current window|the app|the application)"
        )
        state_action = re.fullmatch(
            rf"(minimize|maximize|restore)\s+(?:the\s+)?({relative_target})",
            low,
        )
        if state_action:
            return {
                "skill": f"window.{state_action.group(1)}",
                "params": {"target": active_application},
            }
        if re.fullmatch(
            rf"(?:bring|switch)\s+(?:to\s+)?(?:the\s+)?{relative_target}"
            rf"(?:\s+back)?"
            rf"(?:\s+to\s+(?:the\s+)?front|\s+up)?",
            low,
        ):
            return {"skill": "window.front", "params": {"target": active_application}}
        if re.fullmatch(rf"focus(?:\s+on)?\s+(?:the\s+)?{relative_target}", low):
            return {"skill": "window.focus", "params": {"target": active_application}}

    # Close commands precede open/create/search commands.
    if re.fullmatch(r"(?:close|shut|exit|quit) (?:(?:this|the|current)\s+)*tab", low):
        return {"skill": "browser.close_tab", "params": {"target": "current"}}
    named_tab = re.fullmatch(r"(?:close|shut|exit|quit) (?:the )?(youtube|google) (?:tab|page)", low)
    if named_tab:
        return {"skill": "browser.close_tab", "params": {"target": named_tab.group(1)}}
    if re.fullmatch(r"(?:close|shut|exit|quit) (?:the )?(?:browser|chrome|google chrome)", low):
        return {"skill": "browser.close", "params": {"target": "browser"}}
    if re.fullmatch(
        r"(?:close|shut|exit|quit) "
        r"(?:(?:the|that|this|my) )?"
        r"(?:(?:last|most recently|recently) (?:opened )?)?"
        r"(?:folder|directory|file explorer)"
        r"(?: (?:that |which )?(?:(?:i|you|we) )(?:just |recently )?opened)?",
        low,
    ):
        return {"skill": "app.close", "params": {"target": "__recent_folder__"}}
    if re.fullmatch(
        r"(?:close|shut|exit|quit) "
        r"(?:it|this|that|the application|the app)"
        r"(?: (?:again|now|please|for me))*",
        low,
    ):
        current_folder = str(context.get("current_folder") or "").strip()
        current_application = str(context.get("current_application") or "").strip()
        target = (
            "__recent_folder__"
            if current_folder and current_application.lower() == "file explorer"
            else current_application
        )
        return {"skill": "app.close", "params": {"target": target}}
    if low.startswith(("close ", "shut ", "exit ", "quit ")):
        for alias in sorted(APPLICATION_ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", low):
                return {"skill": "app.close", "params": {"target": alias.title() if alias != "powerpoint" else "PowerPoint"}}

    # Known folders must win over broad browser phrases such as "show me".
    openish = bool(re.search(
        r"\b(?:open|show|go to|navigate to|bring up|pull up|fire up|access|display|load)\b|"
        r"\btake me to\b", low,
    ))
    if openish:
        explicit_path = _extract_explicit_windows_path(request)
        if explicit_path:
            requested_skill = "app.open_folder" if re.search(
                r"\b(?:folder|directory)\b", low,
            ) else "app.open_file" if re.search(r"\bfile\b", low) else "app.open"
            return {"skill": requested_skill, "params": {"target": explicit_path}}
        for alias in sorted(FOLDER_ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b(?:\s+(?:folder|directory))?", low):
                return {"skill": "app.open_folder", "params": {"target": FOLDER_ALIASES[alias]}}

    # Research/document compounds must win over generic "open X" and browser
    # "watch" language.  The action remains a registered JARVIS action.
    research_signal = bool(re.search(
        r"\b(?:research|investigat\w*|study|analysis|literature review|"
        r"reliable (?:information|sources)|source-grounded|cited|citations?)\b|"
        r"\blook\s+into\b", low,
    ))
    report_signal = bool(re.search(r"\b(?:report|paper|document|brief|findings)\b", low))
    research_output_signal = bool(re.search(r"\b(?:report|paper|brief|findings)\b", low))
    creation_signal = bool(re.search(
        r"\b(?:create|make|write|prepare|produce|draft|build|put together)\b", low,
    ))
    word_hint = bool(re.search(r"\b(?:microsoft\s+)?word\b", low))
    if research_output_signal and creation_signal and word_hint and re.search(r"\b(?:about|on|regarding)\b", low):
        research_signal = True
    if research_signal and (creation_signal or report_signal or low.startswith(("research ", "investigate ", "study ", "look into "))):
        topic = _research_topic(request, state)
        live = bool(re.search(
            r"\b(?:live|visibly|progressively|word by word|sentence by sentence)\b|"
            r"(?:watch|see) (?:you )?type|while i watch|in front of me", low,
        ))
        word_requested = word_hint
        if not word_requested:
            word_requested = str(context.get("current_application") or "").lower() in {"word", "microsoft word"}
        report_length = "short" if re.search(r"\b(?:short|brief|concise)\b", low) else "full"
        params = {
            "topic": topic,
            "execution_mode": "LIVE_INTERACTIVE" if live else "FAST_AUTOMATION",
            "report_length": report_length,
        }
        if re.search(r"\b(?:cited|citations?|sources|references|reliable)\b", low):
            params["citations_required"] = True
        if word_requested or live:
            return {"skill": "office_word.create_research_document", "params": params}
        return {"skill": "research.create_report", "params": params}

    current_application = str(context.get("current_application") or "").lower()
    word_context = current_application in {"word", "microsoft word"} or bool(
        re.search(r"\b(?:microsoft\s+)?word\b|\b(?:the|this)\s+document\b", low)
    )
    if word_context and re.match(r"^(?:type|insert|add|write)\b", low):
        supplied = re.sub(
            r"^(?:type|insert|add|write)\s+(?:(?:this|the)\s+)?"
            r"(?:(?:text|paragraph|sentence)\s*)?(?:into\s+(?:word|the document)\s*)?[:,-]?\s*",
            "", request, flags=re.I,
        ).strip(' "\'')
        if supplied and supplied.lower() not in {"it", "this", "that"}:
            return {"skill": "office_word.insert_text", "params": {"text": supplied}}

    save_match = re.match(
        r"^save(?:\s+(?:it|this|the\s+(?:document|file)))?\s+to\s+(.+)$",
        request, re.I,
    )
    if word_context and save_match:
        return {
            "skill": "office_word.save_document",
            "params": {"path": save_match.group(1).strip(' "\'')},
        }

    # A blank Word document is local and never needs a model.
    if (re.search(r"\b(?:create|make|open|start|launch|prepare|bring up)\b", low)
            and not re.search(r"\b(?:about|on|regarding)\s+\S", low)
            and re.search(
        r"\b(?:blank|new)\s+(?:(?:microsoft\s+)?word\s+)?(?:document|file|doc)\b|"
        r"\b(?:microsoft\s+)?word\s+(?:document|file|doc)\b", low,
    )):
        return {"skill": "office_word.create_document", "params": {}}

    office_creation = _classify_office_creation(request)
    if office_creation is not None:
        return office_creation

    # Flexible application launch phrasing.  Keep legacy target spellings so
    # existing registry and close behavior remain unchanged.
    if openish or re.search(r"\b(?:launch|start|run)\b", low):
        for alias in sorted(APPLICATION_ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", low):
                target = alias
                if alias == "word":
                    target = "Word"
                elif alias == "excel":
                    target = "Excel"
                if alias == "powerpoint":
                    target = "PowerPoint"
                elif alias == "file explorer":
                    target = "File Explorer"
                return {"skill": "app.open", "params": {"target": target}}
    return None


def classify_automation_intent(text):
    """Return an allowlist-compatible intent or ``None``."""
    cleaned = normalize_automation_text(text)
    request = _strip_request_scaffolding(cleaned)
    low = request.lower().strip(" .!?")
    if not low:
        return None

    if re.fullmatch(r"(?:emergency stop|stop all actions|stop all automation|abort all actions)", low):
        return _intent("system.emergency_stop", "EMERGENCY_STOP")

    if re.fullmatch(r"(?:go|navigate) back|back to the previous page", low):
        return _intent("browser.back", "BROWSER_BACK")
    if re.fullmatch(r"(?:go|navigate) forward", low):
        return _intent("browser.forward", "BROWSER_FORWARD")
    if re.fullmatch(r"(?:open )?(?:a )?new tab", low):
        return _intent("browser.new_tab", "BROWSER_NEW_TAB")
    if re.fullmatch(r"close (?:this|the current) tab", low):
        return _intent("browser.close_tab", "BROWSER_CLOSE_TAB")
    tab_match = re.fullmatch(r"(?:switch|go|return) to (?:the )?(.+?) tab", low)
    if tab_match:
        return _intent("browser.switch_tab", "BROWSER_SWITCH_TAB", target=tab_match.group(1))

    if re.fullmatch(r"(?:read|summarize|explain) (?:this|the current) (?:page|article|website)", low):
        return _intent("browser.read_page", "READ_PAGE", summarize=not low.startswith("read"))
    find_match = re.fullmatch(r"(?:find|locate|show me) (.+?)(?: on (?:this|the) page)?", low)
    if find_match and any(term in low for term in ("price", "deadline", "button", "contact", "address", "phone", "eligibility", "setting")):
        return _intent("browser.find_on_page", "FIND_ON_PAGE", query=find_match.group(1))

    download = re.fullmatch(r"(?:download|save) (?:this |the )?(.+)", low)
    if download and any(term in low for term in ("file", "pdf", "report", "image", "attachment", "version")):
        return _intent("browser.download", "DOWNLOAD_FILE", target=download.group(1))
    upload = re.fullmatch(r"(?:upload|attach|add) (?:this |the |my )?(.+)", low)
    if upload and any(term in low for term in ("file", "pdf", "document", "image", "transcript", "attachment")):
        return _intent("browser.upload", "UPLOAD_FILE", target=upload.group(1))
    if re.fullmatch(r"(?:submit|send) (?:this |the )?(?:form|application)", low):
        return _intent("browser.submit_form", "SUBMIT_FORM")
    if re.fullmatch(r"(?:fill|complete) (?:in )?(?:this |the )?(?:form|application)|enter my (?:details|information)", low):
        return _intent("browser.fill_form", "FILL_FORM", fields={})

    if re.fullmatch(r"play (?:the )?first (?:result|video)", low):
        return _intent("browser.youtube_play_first", "YOUTUBE_PLAY_FIRST")
    if re.fullmatch(r"pause (?:the )?(?:video|youtube)", low):
        return _intent("browser.pause_video", "PAUSE_VIDEO")
    if re.fullmatch(r"play (?:the )?(?:video|youtube)", low):
        return _intent("browser.play_video", "PLAY_VIDEO")

    gmail_search = re.fullmatch(r"(?:find|search for) (?:the )?(?:emails?|messages?) from (.+)", low)
    if gmail_search:
        return _intent("website.gmail_search", "SEARCH_WEBSITE", query=f"from:{gmail_search.group(1).strip()}")
    if re.fullmatch(r"open (?:the )?latest (?:matching )?(?:email|message)", low):
        return _intent("website.gmail_open_latest", "OPEN_WEBSITE_ITEM")
    if re.fullmatch(r"(?:create|prepare|write) (?:a )?reply draft", low):
        return _intent("website.gmail_reply_draft", "CREATE_DRAFT", body="")
    drive_search = re.fullmatch(r"(?:find|search for) (?:my |the )?(.+?) in (?:google )?drive", low)
    if drive_search:
        return _intent("website.drive_search", "SEARCH_WEBSITE", query=drive_search.group(1).strip())
    if re.fullmatch(r"show (?:me )?(?:its|the file's) folder location", low):
        return _intent("website.drive_show_location", "READ_PAGE")
    stripe_search = re.fullmatch(r"find (?:the )?latest successful payment(?: from (.+))?", low)
    if stripe_search:
        return _intent("website.stripe_search_payment", "SEARCH_WEBSITE", query=(stripe_search.group(1) or "status:successful").strip())

    youtube_search = re.fullmatch(
        r"(?:search youtube(?: for)?|youtube search(?: for)?|find (?:a )?videos?(?: on youtube)?(?: for)?) (.+)",
        low,
    )
    if youtube_search:
        return _intent("browser.search_youtube", "SEARCH_WEBSITE", query=youtube_search.group(1).strip())
    google_search = re.fullmatch(r"(?:search google|google|search the web|look this up)(?: for)? (.+)", low)
    if google_search:
        return _intent("web.search", "SEARCH_WEB", query=google_search.group(1).strip())

    site_names = "|".join(sorted((re.escape(name) for name in SITE_ALIASES), key=len, reverse=True))
    site_match = re.fullmatch(rf"(?:open|go to|show|launch) (?:the )?({site_names})", low)
    if site_match:
        return _intent("browser.open_site", "OPEN_WEBSITE", site=SITE_ALIASES[site_match.group(1)])

    if re.fullmatch(r"(?:open|launch|start) (?:the )?(?:web )?browser", low):
        return _intent("browser.open", "OPEN_BROWSER")

    app_names = "|".join(sorted((re.escape(name) for name in APPLICATION_ALIASES), key=len, reverse=True))
    app_match = re.fullmatch(rf"(?:open|start|launch|bring up|show|i need)(?: microsoft)? (?:a )?({app_names})(?: application| app)?", low)
    if app_match:
        return _intent("app.open", "OPEN_APPLICATION", target=APPLICATION_ALIASES[app_match.group(1)])

    office_creation = _classify_office_creation(request)
    if office_creation is not None:
        return office_creation

    if re.fullmatch(r"(?:save|save this|save the (?:document|workbook|presentation))", low):
        return _intent("office.save", "SAVE_FILE")
    export_match = re.fullmatch(r"(?:export|save) (?:this |it )?as (pdf|csv|xlsx|docx|pptx)", low)
    if export_match:
        return _intent("office.export", "EXPORT_FILE", format=export_match.group(1))

    return None
