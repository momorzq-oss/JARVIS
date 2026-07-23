"""
JARVIS â€” main entry point.

Startup greeting -> wake-word loop -> listen -> route (pending -> fast lane
-> local Qwen router) -> dispatch to skills -> speak the result.
A console window always shows heard text, intent, action and result.
"""
import argparse
import random
import re
import sys
import threading
import time
import traceback

from config import Config, ensure_dirs

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# ---------------------------------------------------------------------------
# Console logging (heard / intent / action / result always visible)
# ---------------------------------------------------------------------------
try:
    import colorama
    colorama.init()
    _C = {"reset": "\033[0m", "dim": "\033[90m", "cyan": "\033[96m",
          "green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m"}
except Exception:
    _C = {k: "" for k in ("reset", "dim", "cyan", "green", "yellow", "red")}


def log(tag, msg, color="dim"):
    try:
        from core.action_manager import ActionManager
        msg = ActionManager._redact_text(msg)
    except Exception:
        msg = str(msg)
    ts = time.strftime("%H:%M:%S")
    col = _C.get(color, "")
    try:
        print(f"{_C['dim']}[{ts}]{_C['reset']} {col}[{tag}]{_C['reset']} {msg}",
              flush=True)
    except Exception:
        pass
    try:
        Config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        filename = ("errors.log" if tag == "error" else
                    "commands.log" if tag in ("heard", "intent", "plan", "result") else
                    "startup.log")
        with (Config.LOG_DIR / filename).open("a", encoding="utf-8") as stream:
            stream.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{tag}] {msg}\n")
    except Exception:
        pass


BANNER = r"""
     â–ˆâ–ˆâ•— â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ•—   â–ˆâ–ˆâ•—â–ˆâ–ˆâ•—â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•—
     â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•—â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•—â–ˆâ–ˆâ•‘   â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â•â•â•
     â–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•‘   â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•—
â–ˆâ–ˆ   â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•—â•šâ–ˆâ–ˆâ•— â–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•‘â•šâ•â•â•â•â–ˆâ–ˆâ•‘
â•šâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•‘  â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•‘  â–ˆâ–ˆâ•‘ â•šâ–ˆâ–ˆâ–ˆâ–ˆâ•”â• â–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•‘
 â•šâ•â•â•â•â• â•šâ•â•  â•šâ•â•â•šâ•â•  â•šâ•â•  â•šâ•â•â•â•  â•šâ•â•â•šâ•â•â•â•â•â•â•
        Local Desktop AI â€” Windows Edition
"""

ACK_LINES = ["Right away, sir.", "At once, sir.", "On it, sir.",
             "Certainly, sir.", "Very good, sir."]
WAKE_ACKS = ["Yes, sir?", "Listening, sir.", "At your service, sir.",
             "How can I help, sir?"]

YES_WORDS = ("yes", "yeah", "yep", "sure", "confirm", "send", "go ahead",
             "do it", "affirmative", "please")
NO_WORDS = ("no", "nope", "cancel", "don't", "dont", "stop", "never mind",
            "nevermind", "negative", "discard")
CANCEL_WORDS = ("never mind", "nevermind", "cancel", "forget it", "stop")


# ---------------------------------------------------------------------------
# Assistant context â€” shared object handed to every skill
# ---------------------------------------------------------------------------
class AssistantContext:
    def __init__(self):
        log("startup", "Assistant context imports starting")
        from brain.llm import LLM
        log("startup", "Assistant context imported LLM")
        from brain.router import Router
        log("startup", "Assistant context imported router")
        from core.registry import SessionRegistry
        from core.live_task import LiveTaskController
        from voice.speaker import Speaker
        from voice.listener import Listener
        log("startup", "Assistant context imported core and voice services")
        from skills.browser import BrowserEngine, set_shared
        log("startup", "Assistant context imported browser engine")
        from skills.desktop_automation import DesktopAutomationService
        from skills.web_automation import BrowserAutomationService
        from skills.website_adapters import WebsiteAutomationService
        log("startup", "Assistant context imported automation services")

        self.llm = LLM()
        self.router = Router()
        log("startup", "Assistant context initialized language services")
        self.registry = SessionRegistry(Config.REGISTRY_FILE)
        log("startup", "Assistant context initialized registry")
        self.speaker = Speaker()
        log("startup", "Assistant context initialized lazy Piper service")
        self.listener = Listener()
        log("startup", "Assistant context initialized registry and audio services")
        self.browser = BrowserEngine(self.registry)
        set_shared(self.browser)
        self.desktop_automation = DesktopAutomationService(self)
        self.web_automation = BrowserAutomationService(self)
        self.website_automation = WebsiteAutomationService(self.web_automation)
        log("startup", "Assistant context initialized automation services")
        self.website_adapters = self.website_automation.adapters
        self.pending = None          # dict: multi-turn state (confirm/music/research)
        self.state = {}              # misc cross-skill state
        self.live_task = LiveTaskController()


class ConsoleSpeaker:
    """Text-only speaker used by --text-only and offline diagnostics."""

    speaking = False

    def speak(self, text, block=False):
        if text:
            print(f"[JARVIS] {text}", flush=True)

    def stop(self):
        return None

    def wait(self, timeout=None):
        return None


# ---------------------------------------------------------------------------
# Dispatch table â€” skill prefix -> module
# ---------------------------------------------------------------------------
def _modules():
    from skills import window_control
    from skills import (system_control, media, news, emailer, whatsapp,
                        research, word_skill, excel_skill, ppt_skill,
                        organizer, coder, chat, university_assignment)
    return {
        "app.": system_control,
        "window.": window_control,
        "system.": system_control,
        "media.": media,
        "news.": news,
        "email.": emailer,
        "whatsapp.": whatsapp,
        "word.": word_skill,
        "office_word.": word_skill,
        "excel.": excel_skill,
        "ppt.": ppt_skill,
        "desktop.": organizer,
        "codex.": coder,
        "research.": research,
        "university.": university_assignment,
        "chat": chat,
        "smalltalk": chat,
    }


SLOW_PREFIXES = ("email.", "news.", "research.", "university.", "word.", "excel.", "ppt.",
                 "office.", "codex.", "whatsapp.", "media.play", "web.", "browser.open")


def _handle_browser(intent, ctx):
    params = intent.get("params", {}) or {}
    if intent["skill"] in {
        "browser.open", "browser.open_site", "browser.search_youtube",
        "browser.search_youtube_and_play", "browser.close",
    } and getattr(ctx, "web_automation", None) is not None:
        return ctx.web_automation.execute(intent)
    if intent["skill"] in {
        "browser.back", "browser.forward", "browser.new_tab", "browser.close_tab",
        "browser.switch_tab", "browser.read_page", "browser.find_on_page",
        "browser.fill_form", "browser.submit_form", "browser.download",
        "browser.upload", "browser.youtube_play_first", "browser.youtube_play_relevant", "browser.play_video",
        "browser.pause_video",
    }:
        return ctx.web_automation.execute(intent)
    if intent["skill"] == "browser.open":
        return ("Browser ready, sir." if ctx.browser.ensure()
                else "I couldn't start the browser, sir.")
    if intent["skill"] == "browser.open_site":
        site = params.get("site", "")
        page = ctx.browser.open_site(site)
        return f"Opening {site}, sir." if page else f"I couldn't open {site}, sir."
    if intent["skill"] == "browser.search_youtube":
        query = params.get("query", "").strip()
        page = ctx.browser.search_youtube(query)
        return (f"Showing YouTube results for {query}, sir."
                if page else f"I couldn't search YouTube for {query}, sir.")
    if intent["skill"] == "browser.close":
        target = (params.get("target") or "browser").strip()
        if target.lower() in ("browser", "the browser", "everything"):
            n = ctx.browser.close_browser()
            return "Browser closed, sir." if n else "The browser isn't open, sir."
        results = ctx.registry.close_by_name(target)
        if results:
            return f"Closed the {target} tab, sir."
        n = ctx.browser.close_tab(target)
        return f"Closed {target}, sir." if n else f"I don't see a {target} tab, sir."
    return None


def _handle_web(intent, ctx):
    query = (intent.get("params", {}) or {}).get("query", "")
    if getattr(ctx, "web_automation", None) is not None:
        return ctx.web_automation.execute(intent)
    page = ctx.browser.search_google(query)
    if page:
        return f"Searching for {query}, sir â€” results on screen."
    return f"I couldn't run that search, sir."


def _dispatch_registered(intent, ctx):
    """Route one intent dict to the right skill. Returns spoken text or None."""
    skill = intent.get("skill", "")
    params = intent.get("params", {}) or {}

    if skill == "system.stop_speech":
        ctx.speaker.stop()
        return None

    if skill == "system.emergency_stop":
        # Signal cancellation and silence output before any optional subsystem
        # cleanup.  Emergency stop must not wait behind browser or UI work.
        state = getattr(ctx, "state", None)
        if isinstance(state, dict):
            state["emergency_stop_generation"] = int(
                state.get("emergency_stop_generation", 0) or 0
            ) + 1
        try:
            ctx.speaker.stop()
        except Exception:
            pass
        task = getattr(ctx, "live_task", None)
        if task is not None:
            task.cancel()
        controller = getattr(ctx, "assistant_controller", None)
        if controller is not None:
            controller.stop_task()
        if getattr(ctx, "web_automation", None) is not None:
            ctx.web_automation.emergency_stop()
        return "Emergency stop completed. All automation input was released."

    if skill.startswith("task."):
        task = getattr(ctx, "live_task", None)
        if task is None:
            return "There is no active controllable task, sir."
        if skill == "task.pause":
            return task.pause()
        if skill == "task.resume":
            return task.resume()
        if skill == "task.cancel":
            return task.cancel()
        if skill == "task.speed":
            return task.set_speed(params.get("direction", "faster"))

    if skill.startswith("hermes."):
        controller = getattr(ctx, "assistant_controller", None)
        if controller is None:
            return "Hermes is unavailable because the JARVIS controller is not running."
        return controller.handle_hermes_intent(skill, params)

    # slow skills get the immediate JARVIS-style acknowledgment
    if any(skill.startswith(p) for p in SLOW_PREFIXES):
        ctx.speaker.speak(random.choice(ACK_LINES), block=False)

    if skill.startswith("browser."):
        return _handle_browser(intent, ctx)
    if skill.startswith("web."):
        return _handle_web(intent, ctx)
    if skill.startswith("office."):
        return ctx.desktop_automation.execute(intent)
    if skill.startswith("website."):
        return ctx.website_automation.execute(intent)

    for prefix, module in _modules().items():
        if skill == prefix or skill.startswith(prefix):
            try:
                return module.handle(intent, ctx)
            except Exception as exc:
                log("error", f"{skill} failed:\n{traceback.format_exc()}", "red")
                return f"The {skill.split('.', 1)[0]} action failed locally: {exc}."

    # absolute fallback: talk about it
    from skills import chat as chat_mod
    return chat_mod.handle(
        {"skill": "chat", "params": {"message": params.get("message", skill)}}, ctx)


def dispatch(intent, ctx):
    """Validate a structured intent, then preserve the existing skill dispatch."""
    manager = getattr(ctx, "action_manager", None)
    if manager is not None:
        try:
            result = manager.execute_intent(
                intent, lambda: _dispatch_registered(intent, ctx)
            )
            from core.command_context import record_result
            record_result(ctx.state, intent, result)
            return result
        except ValueError as exc:
            log("error", str(exc), "red")
            return "I can't execute that because it is not a registered JARVIS action."

    from core.action_manager import ActionManager
    full_skill = intent.get("skill") if isinstance(intent, dict) else None
    if full_skill not in ActionManager.INTENT_ALLOWLIST:
        log("error", f"Unregistered intent: {full_skill}", "red")
        return "I can't execute that because it is not a registered JARVIS action."
    result = _dispatch_registered(intent, ctx)
    from core.command_context import record_result
    record_result(ctx.state, intent, result)
    return result


def handle_registry_command(text, ctx):
    raw_command = (text or "").strip()
    command = raw_command.lower()
    if command.startswith("/trace "):
        from core.command_trace import format_trace
        return format_trace(raw_command[7:].strip(), ctx)
    if command not in {"/help", "/skills", "/status", "/capabilities", "/selftest"}:
        return None
    if command == "/help":
        return "Registry commands: /help, /skills, /status, /capabilities, /selftest, /trace <command>"
    registry = ctx.state.get("capability_registry")
    if registry is None:
        from core.capability_registry import CapabilityRegistry
        registry = CapabilityRegistry()
        ctx.state["capability_registry"] = registry
    if command == "/skills":
        return registry.skills_text()
    if command == "/capabilities":
        return registry.capabilities_text()
    if command == "/selftest":
        registry.discover()
        registry.run_health_checks()
        report = registry.report()
        return f"Self-test complete: {report['total']} capabilities; {report['counts']}"
    from skills.system_control import status_report
    report = registry.report()
    return f"{status_report()} Capability health: {report['counts']}."


# ---------------------------------------------------------------------------
# Pending (multi-turn) handling
# ---------------------------------------------------------------------------
def handle_pending(text, ctx):
    """Returns (handled: bool, spoken: str|None)."""
    pend = ctx.pending
    if pend is None:
        return False, None
    low = (text or "").strip().lower()
    kind = pend.get("kind")

    # universal cancel
    if any(w in low for w in CANCEL_WORDS) and kind != "research":
        ctx.pending = None
        return True, "Cancelled, sir."

    if kind == "confirm":
        if any(w in low for w in YES_WORDS):
            ctx.pending = None
            try:
                result = pend["on_yes"]()
            except Exception as exc:
                result = f"That failed, sir: {exc}."
            return True, result or "Done, sir."
        if any(w in low for w in NO_WORDS):
            ctx.pending = None
            on_no = pend.get("on_no")
            try:
                result = on_no() if on_no else "Cancelled, sir."
            except Exception:
                result = "Cancelled, sir."
            return True, result
        # unclear â€” ask once more, then drop it
        if pend.get("reasked"):
            ctx.pending = None
            return True, "I'll treat that as a no, sir."
        pend["reasked"] = True
        return True, "A simple yes or no, sir?"

    if kind == "music_choice":
        ctx.pending = None
        from skills import media
        return True, media.play(text, ctx)

    if kind == "research":
        from skills import research
        result = research.handle_utterance(text, ctx)
        return True, result

    if kind == "university_assignment":
        from skills import university_assignment
        result = university_assignment.handle_followup(text, ctx)
        return True, result

    if kind == "save_document":
        request = pend.get("request")
        if request is None:
            ctx.pending = None
            return True, "The save request is no longer available, sir."
        if re.match(r"^(?:close|shut|exit|quit)\b", low):
            if request.stage == "confirm":
                return True, (
                    "This document is still unsaved. Say yes to save it at "
                    f"{request.resolved_path}, or no to cancel the save before closing."
                )
            return True, (
                "This document is still unsaved. Please choose a save location, "
                "or say cancel before closing it."
            )
        if request.stage == "location":
            path = request.resolve(text)
            if path is None:
                return True, "I couldn't resolve that location. Please name Desktop, Downloads, Documents, OneDrive, or a complete path."
            effects = []
            if request.directory_creation_required:
                effects.append("The destination folder will be created.")
            if request.overwrite_required:
                effects.append("The file already exists and would be overwritten.")
            suffix = " " + " ".join(effects) if effects else ""
            return True, f"I'll save it as {path}.{suffix} Is that correct?"
        if request.stage == "confirm":
            if any(word in low for word in YES_WORDS):
                try:
                    ok = request.save()
                except Exception as exc:
                    ctx.pending = None
                    return True, f"The document was not saved: {exc}."
                ctx.pending = None
                return True, (f"Saved and verified at {request.resolved_path}, sir."
                              if ok else "The save did not verify successfully, sir.")
            if any(word in low for word in NO_WORDS + CANCEL_WORDS):
                ctx.pending = None
                return True, "Save cancelled, sir."
            return True, "Please say yes to save there, or no to cancel."

    # unknown pending type â€” clear and fall through
    ctx.pending = None
    return False, None


# ---------------------------------------------------------------------------
# Utterance pipeline
# ---------------------------------------------------------------------------
def handle_utterance(text, ctx):
    from core.command_text import cleanup_command
    from core.command_pipeline import select_route

    text = cleanup_command(text)
    if not text:
        return None
    command_stop_generation = int(
        ctx.state.get("emergency_stop_generation", 0) or 0
    )

    def speech_allowed():
        return int(ctx.state.get("emergency_stop_generation", 0) or 0) == command_stop_generation

    ctx.state["last_command_text"] = text
    log("heard", f"user input received ({len(text)} characters)", "cyan")

    registry_response = handle_registry_command(text, ctx)
    if registry_response is not None:
        log("result", f"registry response generated ({len(registry_response)} characters)", "green")
        ctx.speaker.speak(registry_response)
        return registry_response

    route = select_route(text, ctx, source="voice" if ctx.state.get("input_source") == "voice" else "typed")
    intent = route.get("intent")

    # Barge-in / stop always wins, even mid-pending.
    if intent and intent["skill"] == "system.stop_speech":
        ctx.speaker.stop()
        log("intent", "system.stop_speech", "yellow")
        return None

    if route["route_type"] == "pending":
        handled, spoken = handle_pending(text, ctx)
        if handled:
            if spoken:
                log("result", f"pending response generated ({len(spoken)} characters)", "green")
                if speech_allowed():
                    ctx.speaker.speak(spoken)
            return spoken

    plan = route.get("plan") or []
    if route["route_type"] == "plan" and plan:
        results = []
        for index, planned_intent in enumerate(plan, 1):
            if not speech_allowed():
                break
            log(
                "plan",
                f"{index}/{len(plan)} {planned_intent.get('skill')} "
                f"params={sorted((planned_intent.get('params') or {}).keys())}",
                "yellow",
            )
            controller = getattr(ctx, "assistant_controller", None)
            if controller is not None:
                controller._emit(
                    "timeline", "planner_step",
                    f"{index}/{len(plan)} {planned_intent}",
                )
            result = dispatch(planned_intent, ctx)
            if not speech_allowed():
                break
            if result:
                results.append(result)
                log("result", f"step response generated ({len(result)} characters)", "green")
                low_result = result.lower()
                if any(marker in low_result for marker in (
                    "couldn't", "could not", "can't find", "needs the openrouter key",
                    "no research report", "no sources", "no completed draft",
                )):
                    break
        spoken = " ".join(results)
        if spoken and speech_allowed():
            ctx.speaker.speak(spoken)
        return spoken

    if intent is None:
        intent = {"skill": "chat", "params": {"message": text}}
    log(
        "intent",
        f"{intent['skill']} params={sorted((intent.get('params') or {}).keys())}",
        "yellow",
    )

    spoken = dispatch(intent, ctx)
    if spoken:
        log("result", f"response generated ({len(spoken)} characters)", "green")
        # Keep emergency stop silent after dispatch has cancelled playback.
        # Its completion remains available to the GUI via the returned text;
        # starting Piper again here would undo the user's stop request.
        if intent.get("skill") != "system.emergency_stop" and speech_allowed():
            ctx.speaker.speak(spoken)
    return spoken


# ---------------------------------------------------------------------------
# Barge-in monitor â€” "Jarvis stop" silences speech instantly
# ---------------------------------------------------------------------------
def barge_monitor(ctx, stop_event):
    while not stop_event.is_set():
        try:
            if ctx.speaker.speaking:
                heard = ctx.listener.listen_quick(max_seconds=1.6)
                if heard and "stop" in heard.lower():
                    log("barge-in", f"stop phrase detected ({len(heard)} characters)", "red")
                    ctx.speaker.stop()
            else:
                time.sleep(0.25)
        except Exception:
            time.sleep(0.5)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
def greeting():
    hour = time.localtime().tm_hour
    daypart = ("morning" if hour < 12 else
               "afternoon" if hour < 18 else "evening")
    a = Config.OWNER_ADDRESS
    return (f"Good {daypart}, {a}. All systems are operational. "
            f"How may I assist?")


def preload_models(ctx):
    """Load whisper + router in the background so the first command is fast."""
    log("init", "preloading speech model...", "dim")
    try:
        ctx.listener.preload()
        if ctx.listener.load_error:
            log("init", f"whisper failed: {ctx.listener.load_error}", "red")
        else:
            log("init", "speech model ready", "green")
    except Exception as exc:
        log("init", f"whisper failed: {exc}", "red")
    log("init", "preloading router model...", "dim")
    try:
        ctx.router.preload()
        if ctx.router.load_error:
            log("init", f"router failed: {ctx.router.load_error}", "red")
        else:
            log("init", "router model ready", "green")
    except Exception as exc:
        log("init", f"router failed: {exc}", "red")


def typed_loop(ctx):
    """Fallback: no wake word / no mic â€” type commands in the console."""
    log("mode", "typed-command mode (wake word unavailable)", "yellow")
    ctx.speaker.speak("Voice activation is unavailable, sir. "
                      "Type your commands in the console.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("exit", "quit"):
            break
        if text:
            handle_utterance(text, ctx)
            ctx.speaker.wait(timeout=30)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="JARVIS desktop AI assistant")
    parser.add_argument(
        "--text-only", action="store_true", help="use console input without voice"
    )
    parser.add_argument(
        "--debug", action="store_true", help="show full tracebacks for skill errors"
    )
    parser.add_argument(
        "--skip-model-preload",
        action="store_true",
        help="skip background Whisper and router preload for faster startup testing",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    ensure_dirs()
    print(BANNER, flush=True)
    log("init", "desktop path resolved", "dim")
    log("init", "data path resolved", "dim")

    ctx = AssistantContext()
    ctx.debug = args.debug
    if args.text_only:
        ctx.speaker.stop()
        ctx.speaker = ConsoleSpeaker()

    if not Config.OPENROUTER_API_KEY:
        log("init", "OPENROUTER_API_KEY missing â€” conversation/drafting "
                    "skills will be limited (see .env.example)", "red")

    if args.skip_model_preload:
        log("init", "model preload skipped", "yellow")
    else:
        threading.Thread(target=preload_models, args=(ctx,), daemon=True).start()

    if args.text_only:
        typed_loop(ctx)
        return 0

    # startup greeting (varies by time of day)
    ctx.speaker.speak(greeting(), block=True)

    # barge-in monitor
    stop_event = threading.Event()
    threading.Thread(target=barge_monitor, args=(ctx, stop_event),
                     daemon=True).start()

    # wake-word loop
    try:
        from voice.wakeword import WakeWordEngine
        wake = WakeWordEngine()
    except Exception as exc:
        log("wake", f"voice initialization failed: {exc}", "red")
        typed_loop(ctx)
        return 0
    if not wake._ensure_loaded():
        log("wake", f"wake word unavailable: {wake.load_error}", "red")
        typed_loop(ctx)
        return 0

    log("wake", f"say 'Hey Jarvis' to begin (threshold {wake.threshold})", "green")
    print("-" * 60, flush=True)

    try:
        while True:
            if not wake.wait(stop_event=stop_event):
                break
            if ctx.speaker.speaking:
                ctx.speaker.stop()
            ctx.speaker.speak(random.choice(WAKE_ACKS), block=True)
            time.sleep(0.15)
            text = ctx.listener.listen()
            if not text:
                ctx.speaker.speak("I didn't catch that, sir.")
                continue
            handle_utterance(text, ctx)
            ctx.speaker.wait(timeout=60)
            print("-" * 60, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        ctx.speaker.speak("Powering down, sir. Until next time.")
        time.sleep(1.2)
        try:
            ctx.browser.close_browser()
        except Exception:
            pass
        log("exit", "goodbye", "dim")


if __name__ == "__main__":
    sys.exit(main())
