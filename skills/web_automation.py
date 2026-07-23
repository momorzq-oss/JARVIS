"""Verified Playwright operations for visible, cancellable web automation."""
from __future__ import annotations

import dataclasses
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from config import Config


def _query_terms(value):
    """Small local tokenizer used only to rank already-visible YouTube titles."""
    stop_words = {
        "a", "an", "and", "about", "for", "how", "in", "is", "it", "of",
        "on", "the", "to", "with",
    }
    return {
        word for word in re.findall(r"[a-z0-9]+", str(value).lower())
        if len(word) > 1 and word not in stop_words
    }


@dataclasses.dataclass
class WebActionResult:
    status: str
    action: str
    message: str
    website: str = ""
    page_title: str = ""
    url: str = ""
    error: str = ""
    recovery_attempt: str = ""
    downloaded_file_path: str = ""
    uploaded_file_path: str = ""
    approval_status: str = "not_required"
    data: object = None


class WebActionLogger:
    def write(self, result, *, command="", intent=""):
        from core.action_manager import ActionManager
        sensitive_domains = ("mail.google.com", "drive.google.com", "dashboard.stripe.com")
        private_page = any(
            result.website == domain or result.website.endswith("." + domain)
            for domain in sensitive_domains
        )
        result_text = result.message
        if result.action == "read_page":
            result_text = f"Read {len(str(result.data or ''))} characters from the active page"
        entry = {
            "timestamp": time.time(),
            "voice_command": ActionManager._redact_text(command),
            "detected_intent": intent,
            "website": result.website,
            "page_title": "[PRIVATE PAGE]" if private_page else ActionManager._redact_text(result.page_title),
            "action": result.action,
            "result": ActionManager._redact_text(result_text),
            "error": ActionManager._redact_text(result.error),
            "recovery_attempt": ActionManager._redact_text(result.recovery_attempt),
            "downloaded_file_path": ActionManager._redact_text(result.downloaded_file_path),
            "uploaded_file_path": ActionManager._redact_text(result.uploaded_file_path),
            "approval_status": result.approval_status,
        }
        Config.WEB_ACTION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with Config.WEB_ACTION_LOG_FILE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def page_domain(page):
    try:
        return (urlparse(page.url).hostname or "").lower()
    except Exception:
        return ""


class BrowserAutomationService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.browser = ctx.browser
        self.logger = WebActionLogger()
        self._stop = threading.Event()

    def _checkpoint(self):
        if self._stop.is_set():
            raise RuntimeError("Browser automation stopped by user")
        task = getattr(self.ctx, "live_task", None)
        if task is not None:
            task.checkpoint()

    def _remember_browser_context(self, destination, *, query="", action="",
                                  content_type="web_page", page=None):
        """Keep only the minimal context needed for local browser follow-ups."""
        previous = self.ctx.state.get("browser_context", {})
        previous = previous if isinstance(previous, dict) else {}
        self.ctx.state["browser_context"] = {
            "destination": str(destination or previous.get("destination") or "").lower(),
            "query": str(query or previous.get("query") or "").strip(),
            "action": str(action or previous.get("action") or ""),
            "content_type": str(content_type or previous.get("content_type") or "web_page"),
            "url": getattr(page, "url", "") if page is not None else previous.get("url", ""),
            "last_focused_at": time.time(),
        }

    def _active_page(self):
        if not self.browser.ensure():
            return None
        pages = list(getattr(self.browser.context, "pages", []) or [])
        for page in reversed(pages):
            try:
                if not page.is_closed():
                    return page
            except Exception:
                continue
        return None

    def _result(self, status, action, message, page=None, **kwargs):
        title = ""
        url = ""
        if page is not None:
            try:
                title = page.title()
            except Exception:
                pass
            try:
                url = page.url
            except Exception:
                pass
        return WebActionResult(status, action, message, page_domain(page) if page else "",
                               title, url, **kwargs)

    def _log(self, result, intent="", command=""):
        command = command or self.ctx.state.get("last_command_text", "")
        intent = intent or self.ctx.state.get("active_web_intent", "")
        self.logger.write(result, command=command, intent=intent)
        return result

    def verify_domain(self, page, expected_domains):
        expected = tuple(str(item).lower().lstrip(".") for item in expected_domains)
        domain = page_domain(page)
        return bool(domain and any(domain == item or domain.endswith("." + item) for item in expected))

    def open_browser(self):
        self._checkpoint()
        ok = self.browser.ensure()
        if ok:
            self._remember_browser_context("browser", action="open")
        return self._log(self._result("success" if ok else "failed", "open_browser",
                                     "Browser ready." if ok else "The browser could not be started."))

    def open_website(self, site):
        self._checkpoint()
        page = self.browser.open_site(site)
        if page is None:
            return self._log(self._result("failed", "open_website", f"Could not open {site}."))
        self.ctx.state["active_website"] = str(site).lower().strip()
        self._remember_browser_context(site, action="open", page=page)
        return self._log(self._result("success", "open_website", f"Opened {site} and verified the page.", page))

    def search_web(self, query):
        self._checkpoint()
        page = self.browser.search_google(query)
        if page is None:
            return self._log(self._result("failed", "search_web", "Web search failed."))
        self.ctx.state["active_website"] = "google"
        self._remember_browser_context("google", query=query, action="search", page=page)
        return self._log(self._result("success", "search_web", f"Google results for {query} are visible.", page))

    def search_youtube(self, query):
        self._checkpoint()
        page = self.browser.search_youtube(query)
        if page is None:
            return self._log(self._result("failed", "search_youtube", "YouTube search failed."))
        self.ctx.state["active_website"] = "youtube"
        self._remember_browser_context("youtube", query=query, action="search", content_type="video", page=page)
        return self._log(self._result("success", "search_youtube", f"YouTube results for {query} are visible.", page))

    def search_youtube_and_play(self, query, selection="most_relevant"):
        """Search YouTube, then choose a locally ranked normal-video result."""
        searched = self.search_youtube(query)
        if searched.status != "success":
            return searched
        return self.youtube_play_relevant(query, selection=selection)

    def back(self):
        page = self._active_page()
        if page is None:
            return self._log(self._result("failed", "back", "No active browser page."))
        self._checkpoint()
        page.go_back(wait_until="domcontentloaded", timeout=30000)
        return self._log(self._result("success", "back", "Returned to the previous page.", page))

    def forward(self):
        page = self._active_page()
        if page is None:
            return self._log(self._result("failed", "forward", "No active browser page."))
        self._checkpoint()
        page.go_forward(wait_until="domcontentloaded", timeout=30000)
        return self._log(self._result("success", "forward", "Moved to the next page.", page))

    def new_tab(self, url="about:blank"):
        if not self.browser.ensure():
            return self._log(self._result("failed", "new_tab", "Browser unavailable."))
        self._checkpoint()
        page = self.browser.context.new_page()
        if url and url != "about:blank":
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self._remember_browser_context("browser", action="new_tab", page=page)
        return self._log(self._result("success", "new_tab", "Opened a new browser tab.", page))

    def close_tab(self, target=""):
        """Close the current or a named JARVIS-owned Playwright tab only."""
        page = None
        target_low = str(target or "").strip().lower()
        named_target = bool(target_low and target_low not in {"current", "this", "last"})
        if named_target:
            try:
                for candidate in reversed(list(self.browser.context.pages)):
                    title = candidate.title().lower()
                    url = str(candidate.url).lower()
                    if target_low in title or target_low in url:
                        page = candidate
                        break
            except Exception:
                page = None
            if page is None:
                return self._log(self._result(
                    "failed", "close_tab",
                    f"No JARVIS tab matching {target} is open.",
                ))
        if page is None:
            page = self._active_page()
        if page is None:
            return self._log(self._result("failed", "close_tab", "No active browser tab."))
        title = ""
        try:
            title = page.title()
            page.close()
        except Exception as exc:
            return self._log(self._result("failed", "close_tab", "The tab could not be closed.", error=str(exc)))
        self._remember_browser_context("", action="close_tab")
        return self._log(self._result("success", "close_tab", f"Closed {title or 'the current tab'}."))

    def close_browser(self):
        count = self.browser.close_browser()
        self.ctx.state.pop("active_website", None)
        message = "Browser closed." if count else "The browser was already closed."
        return self._log(self._result("success", "close_browser", message))

    def switch_tab(self, target):
        if not self.browser.ensure():
            return self._log(self._result("failed", "switch_tab", "Browser unavailable."))
        target_low = str(target).lower()
        for page in reversed(list(self.browser.context.pages)):
            try:
                if target_low in page.title().lower() or target_low in page.url.lower():
                    page.bring_to_front()
                    return self._log(self._result("success", "switch_tab", f"Switched to {target}.", page))
            except Exception:
                continue
        return self._log(self._result("failed", "switch_tab", f"No tab matching {target} was found."))

    def read_page(self, summarize=False, max_chars=6000):
        page = self._active_page()
        if page is None:
            return self._log(self._result("failed", "read_page", "No active browser page."))
        self._checkpoint()
        try:
            text = page.locator("body").inner_text(timeout=15000)
            text = re.sub(r"\s+", " ", text).strip()[:max_chars]
            if summarize and getattr(self.ctx.llm, "available", False):
                summary = self.ctx.llm.quick(
                    "Summarize this webpage in five factual sentences. Do not expose private values.\n\n" + text,
                    max_tokens=350,
                )
                text = summary or text
            return self._log(self._result("success", "read_page", text or "The page contains no readable text.", page, data=text))
        except Exception as exc:
            return self._log(self._result("failed", "read_page", "The page could not be read.", page, error=str(exc)))

    def find_on_page(self, query):
        page = self._active_page()
        if page is None:
            return self._log(self._result("failed", "find_on_page", "No active browser page."))
        self._checkpoint()
        try:
            locator = page.get_by_text(str(query), exact=False).first
            locator.scroll_into_view_if_needed(timeout=8000)
            text = locator.inner_text(timeout=5000).strip()
            return self._log(self._result("success", "find_on_page", f"Found {text or query} and scrolled it into view.", page, data=text))
        except Exception as exc:
            return self._log(self._result("failed", "find_on_page", f"Could not find {query} on this page.", page, error=str(exc)))

    def fill_form(self, fields):
        page = self._active_page()
        if page is None:
            return self._log(self._result("failed", "fill_form", "No active form page."))
        if not isinstance(fields, dict) or not fields:
            return self._log(self._result("failed", "fill_form", "No form values were provided.", page))
        completed = []
        try:
            for label, value in fields.items():
                self._checkpoint()
                candidates = (
                    page.get_by_label(str(label), exact=False),
                    page.locator(f"[name='{str(label)}']"),
                    page.get_by_placeholder(str(label), exact=False),
                )
                filled = False
                for locator in candidates:
                    try:
                        if locator.count() and locator.first.is_visible():
                            locator.first.fill(str(value))
                            filled = True
                            completed.append(str(label))
                            break
                    except Exception:
                        continue
                if not filled:
                    raise RuntimeError(f"Field not found: {label}")
            message = f"Filled {len(completed)} fields and stopped before submission."
            result = self._result("success", "fill_form", message, page, data={"fields": completed})
            return self._log(result)
        except Exception as exc:
            return self._log(self._result("failed", "fill_form", "Form completion stopped safely.", page, error=str(exc), data={"fields": completed}))

    def submit_form(self, selector=""):
        page = self._active_page()
        if page is None:
            return self._log(self._result("failed", "submit_form", "No active form page."))
        self._checkpoint()
        try:
            locator = page.locator(selector).first if selector else page.get_by_role(
                "button", name=re.compile(r"^(submit|send|apply|confirm|place order|pay|refund)$", re.I)
            ).first
            locator.click(timeout=10000)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            return self._log(self._result("success", "submit_form", "The approved form action was submitted.", page, approval_status="approved_once"))
        except Exception as exc:
            return self._log(self._result("failed", "submit_form", "Submission failed safely.", page, error=str(exc), approval_status="approved_once"))

    def download(self, target):
        page = self._active_page()
        if page is None:
            return self._log(self._result("failed", "download", "No active download page."))
        folder = Config.DOWNLOADS_PATH / "Jarvis Downloads"
        folder.mkdir(parents=True, exist_ok=True)
        self._checkpoint()
        try:
            with page.expect_download(timeout=30000) as pending:
                page.get_by_text(str(target), exact=False).first.click(timeout=10000)
            download = pending.value
            path = folder / descriptive_download_name(download.suggested_filename)
            download.save_as(str(path))
            if not path.exists():
                raise RuntimeError("Downloaded file was not found")
            return self._log(self._result("success", "download", f"Downloaded and verified {path.name}.", page, downloaded_file_path=str(path)))
        except Exception as exc:
            return self._log(self._result("failed", "download", "Download failed safely.", page, error=str(exc)))

    def upload(self, target):
        page = self._active_page()
        if page is None:
            return self._log(self._result("failed", "upload", "No active upload page."))
        path = Path(str(target)).expanduser()
        if not path.is_file():
            return self._log(self._result("failed", "upload", "The requested upload file was not found.", page))
        self._checkpoint()
        try:
            page.locator("input[type=file]").first.set_input_files(str(path))
            return self._log(self._result("success", "upload", f"Uploaded {path.name} and stopped before submission.", page, uploaded_file_path=str(path), approval_status="approved_once"))
        except Exception as exc:
            return self._log(self._result("failed", "upload", "Upload failed safely.", page, error=str(exc), approval_status="approved_once"))

    def youtube_play_first(self):
        return self.youtube_play_relevant("")

    def youtube_play_relevant(self, query, selection="most_relevant"):
        """Pick the strongest locally relevant YouTube video, never an ad/Short."""
        page = self._active_page()
        if page is None or not self.verify_domain(page, ("youtube.com",)):
            return self._log(self._result("failed", "youtube_play_relevant", "The active tab is not YouTube.", page))
        self._checkpoint()
        try:
            selector = "ytd-video-renderer a#video-title[href*='/watch']"
            # YouTube renders result cards after DOMContentLoaded.  Counting
            # immediately creates a false "no result" failure on ordinary
            # connections, so wait for one usable normal-video link first.
            waiter = getattr(page, "wait_for_selector", None)
            if callable(waiter):
                waiter(selector, state="attached", timeout=15000)
            self._checkpoint()
            candidates = page.locator(selector)
            count = min(candidates.count(), 12)
            terms = _query_terms(query)
            ranked = []
            for index in range(count):
                candidate = candidates.nth(index)
                title = (candidate.get_attribute("title") or candidate.inner_text() or "").strip()
                href = (candidate.get_attribute("href") or "").lower()
                title_low = title.lower()
                if not title or "/shorts/" in href or "live" in title_low:
                    continue
                title_terms = _query_terms(title)
                overlap = len(terms & title_terms)
                if terms and not overlap:
                    continue
                score = overlap * 10
                if any(word in title_low for word in ("tutorial", "guide", "explained", "learn", "course")):
                    score += 3
                # Stable result ordering breaks equal scores without treating a
                # popular or sponsored item as objectively "best".
                ranked.append((score, -index, title, candidate))
            if not ranked:
                return self._log(self._result(
                    "failed", "youtube_play_relevant",
                    "No clearly relevant normal video result was found.", page,
                ))
            _score, _order, selected_title, selected = max(ranked, key=lambda item: item[:2])
            selected.click(timeout=15000)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            try:
                page.locator("video").first.evaluate("video => video.play()")
            except Exception:
                pass  # A click normally starts playback; browser policy may require it.
            self._remember_browser_context("youtube", query=query, action="play", content_type="video", page=page)
            return self._log(self._result(
                "success", "youtube_play_relevant",
                f"I selected the most relevant result I found: {selected_title}.", page,
                data={"selection": selection or "most_relevant", "title": selected_title},
            ))
        except Exception as exc:
            return self._log(self._result("failed", "youtube_play_relevant", "Could not open the selected YouTube result.", page, error=str(exc)))

    def video_control(self, action):
        page = self._active_page()
        if page is None:
            return self._log(self._result("failed", f"{action}_video", "No active video page."))
        self._checkpoint()
        try:
            page.locator("video").first.evaluate(f"element => element.{action}()")
            return self._log(self._result("success", f"{action}_video", f"Video {action}d.", page))
        except Exception as exc:
            return self._log(self._result("failed", f"{action}_video", f"Video {action} failed.", page, error=str(exc)))

    def detect_login_state(self):
        page = self._active_page()
        if page is None:
            return "unavailable"
        try:
            if page.locator("iframe[src*='captcha'], [class*='captcha'], [id*='captcha']").count():
                return "captcha_required"
            if page.locator("input[type=password]").count():
                return "login_required"
            body = page.locator("body").inner_text(timeout=5000).lower()
            if any(term in body for term in ("two-factor", "two factor", "verification code", "passkey")):
                return "verification_required"
            return "ready"
        except Exception:
            return "unknown"

    def emergency_stop(self):
        self._stop.set()
        try:
            # Never call the context property here: it calls ensure() and can
            # launch a browser while JARVIS is trying to stop everything.
            context = getattr(self.browser, "_context", None)
            for page in list(getattr(context, "pages", []) or []):
                try:
                    page.evaluate("window.stop()")
                except Exception:
                    pass
        except Exception:
            pass
        return self._log(self._result("success", "emergency_stop", "All browser automation stopped."))

    def resume(self):
        self._stop.clear()
        return self._log(self._result("success", "resume", "Browser automation resumed."))

    def execute(self, intent):
        skill = intent.get("skill", "")
        params = dict(intent.get("params", {}) or {})
        intent_group = params.pop("intent_group", skill)
        self.ctx.state["active_web_intent"] = intent_group
        operations = {
            "browser.open": lambda: self.open_browser(),
            "browser.open_site": lambda: self.open_website(params.get("site", "")),
            "web.search": lambda: self.search_web(params.get("query", "")),
            "browser.search_youtube": lambda: self.search_youtube(params.get("query", "")),
            "browser.search_youtube_and_play": lambda: self.search_youtube_and_play(
                params.get("query", ""), params.get("selection", "most_relevant"),
            ),
            "browser.close": self.close_browser,
            "browser.back": self.back,
            "browser.forward": self.forward,
            "browser.new_tab": lambda: self.new_tab(params.get("url", "about:blank")),
            "browser.close_tab": lambda: self.close_tab(params.get("target", "")),
            "browser.switch_tab": lambda: self.switch_tab(params.get("target", "")),
            "browser.read_page": lambda: self.read_page(bool(params.get("summarize"))),
            "browser.find_on_page": lambda: self.find_on_page(params.get("query", "")),
            "browser.fill_form": lambda: self.fill_form(params.get("fields", {})),
            "browser.submit_form": lambda: self.submit_form(params.get("selector", "")),
            "browser.download": lambda: self.download(params.get("target", "")),
            "browser.upload": lambda: self.upload(params.get("target", "")),
            "browser.youtube_play_first": self.youtube_play_first,
            "browser.youtube_play_relevant": lambda: self.youtube_play_relevant(
                params.get("query", ""), params.get("selection", "most_relevant"),
            ),
            "browser.play_video": lambda: self.video_control("play"),
            "browser.pause_video": lambda: self.video_control("pause"),
        }
        operation = operations.get(skill)
        if operation is None:
            raise ValueError(f"Unsupported browser automation intent: {skill}")
        result = operation()
        return result.message


def descriptive_download_name(value):
    name = Path(str(value or "download")).name
    return re.sub(r"[<>:\"/\\|?*]+", "_", name).strip(" .") or "download"
