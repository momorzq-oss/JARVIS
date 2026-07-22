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
    r"information|me|about|on|for|to|of|with|explaining|explain|show me|look up)\b",
    re.I,
)
_BROWSER_STOP_WORDS = {
    "a", "an", "and", "about", "for", "how", "i", "in", "is", "it",
    "me", "my", "of", "on", "or", "please", "the", "this", "to", "with",
}


def _clean_browser_query(value):
    """Remove request scaffolding while leaving the user topic untouched."""
    query = str(value or "").strip(" .,!?:;-\t\r\n")
    query = re.sub(
        r"^(?:and|then|for|about|on|regarding|of)\s+", "", query, flags=re.I,
    )
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
            return match.group(1).strip(" .")
    return ""


def _document_type(text):
    low = text.lower()
    return next((kind for kind in DOCUMENT_TYPES if kind in low), "document")


def classify_automation_intent(text):
    """Return an allowlist-compatible intent or ``None``."""
    cleaned = normalize_automation_text(text)
    low = cleaned.lower().strip(" .!?")
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

    if any(noun in low for noun in ("spreadsheet", "workbook", "budget", "tracker", "expense sheet")) and any(verb in low for verb in ("create", "make", "build", "prepare")):
        topic = _extract_topic(cleaned, (r"(?:about|for|on)",))
        if not topic:
            topic = re.sub(r"^(?:create|make|build|prepare) (?:a |an )?", "", cleaned, flags=re.I)
            topic = re.sub(r"\s+in (?:microsoft )?excel[.!?]*$", "", topic, flags=re.I).strip(" .")
        return _intent("office.create_spreadsheet", "CREATE_SPREADSHEET", topic=topic, mode=_mode(cleaned), save_after_completion=True)

    if any(noun in low for noun in ("presentation", "slides", "slide deck", "pitch deck")) and any(verb in low for verb in ("create", "make", "build", "prepare")):
        topic = _extract_topic(cleaned, (r"(?:about|for|on)",)) or "Presentation"
        slide_match = re.search(r"\b(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")[- ]slide", low)
        slide_count = 10
        if slide_match:
            slide_count = int(slide_match.group(1)) if slide_match.group(1).isdigit() else NUMBER_WORDS[slide_match.group(1)]
        return _intent("office.create_presentation", "CREATE_PRESENTATION", topic=topic, slides=slide_count, mode=_mode(cleaned), save_after_completion=True)

    if any(verb in low for verb in ("create", "write", "prepare", "make", "draft", "put together")) and any(kind in low for kind in DOCUMENT_TYPES):
        kind = _document_type(cleaned)
        topic = _extract_topic(cleaned, (r"(?:about|for|on)",))
        return _intent("office.create_document", "CREATE_DOCUMENT", document_type=kind, topic=topic, mode=_mode(cleaned), save_after_completion=True)

    if re.fullmatch(r"(?:save|save this|save the (?:document|workbook|presentation))", low):
        return _intent("office.save", "SAVE_FILE")
    export_match = re.fullmatch(r"(?:export|save) (?:this |it )?as (pdf|csv|xlsx|docx|pptx)", low)
    if export_match:
        return _intent("office.export", "EXPORT_FILE", format=export_match.group(1))

    return None
