"""
Intent routing, two layers:

1. FAST LANE â€” hardcoded regex rules for instant commands (open/close/
   volume/screenshot/thanks/stop/pause...). Zero model calls, ~0 ms.
2. ROUTER BRAIN â€” Qwen2.5-0.5B-Instruct loaded locally with transformers.
   Classifies anything the fast lane didn't catch into
   {"skill": ..., "params": {...}}. Target < 1 s on CPU.
"""
import json
import os
import importlib
import re
import sys
import threading
import traceback

from config import Config
from brain.prompts import ROUTER_SYSTEM_PROMPT

# ==========================================================================
# 1. FAST LANE â€” ordered rules; first match wins.
# ==========================================================================
def _rgx(pattern):
    return re.compile(pattern, re.IGNORECASE)


FAST_RULES = [
    # --- stop talking (barge-in also handled separately) ------------------
    (_rgx(r"^(?:jarvis[, ]*)?(?:stop|stop talking|shut up|be quiet|silence)[.! ]*$"),
     lambda m: {"skill": "system.stop_speech", "params": {}}),

    # --- volume ------------------------------------------------------------
    (_rgx(r"(?:turn )?(?:the )?volume up|louder|increase (?:the )?volume"),
     lambda m: {"skill": "system.volume", "params": {"action": "up"}}),
    (_rgx(r"(?:turn )?(?:the )?volume down|quieter|decrease (?:the )?volume|lower (?:the )?volume"),
     lambda m: {"skill": "system.volume", "params": {"action": "down"}}),
    (_rgx(r"^unmute(?: (?:the )?(?:volume|sound|audio))?$"),
     lambda m: {"skill": "system.volume", "params": {"action": "unmute"}}),
    (_rgx(r"^mute(?: (?:the )?(?:volume|sound|audio))?$"),
     lambda m: {"skill": "system.volume", "params": {"action": "mute"}}),

    # --- system -------------------------------------------------------------
    (_rgx(r"(?:take a |take |capture a )?screen\s?shot"),
     lambda m: {"skill": "system.screenshot", "params": {}}),
    (_rgx(r"^lock (?:the )?(?:pc|computer|screen|workstation)$"),
     lambda m: {"skill": "system.lock", "params": {}}),
    (_rgx(r"cancel (?:the )?shutdown|abort (?:the )?shutdown"),
     lambda m: {"skill": "system.shutdown", "params": {"action": "cancel"}}),
    (_rgx(r"^(?:restart|reboot) (?:the )?(?:pc|computer|machine)$"),
     lambda m: {"skill": "system.shutdown", "params": {"action": "restart"}}),
    (_rgx(r"^(?:sleep|put) (?:the )?(?:pc|computer|machine)(?: to sleep)?$"),
     lambda m: {"skill": "system.shutdown", "params": {"action": "sleep"}}),
    (_rgx(r"^(?:shut ?down|power off|turn off) (?:the )?(?:pc|computer|machine)$"),
     lambda m: {"skill": "system.shutdown", "params": {"action": "shutdown"}}),
    (_rgx(r"(?:battery|system) (?:status|report)|how(?:'s| is) my (?:pc|computer|battery)|status report"),
     lambda m: {"skill": "system.status", "params": {}}),

    # --- active task control ------------------------------------------------
    (_rgx(r"^(?:pause typing|pause (?:the )?(?:current )?task)[.! ]*$"),
     lambda m: {"skill": "task.pause", "params": {}}),
    (_rgx(r"^(?:resume typing|resume (?:the )?(?:current )?task)[.! ]*$"),
     lambda m: {"skill": "task.resume", "params": {}}),
    (_rgx(r"^(?:cancel|stop) (?:the )?(?:current )?task[.! ]*$"),
     lambda m: {"skill": "task.cancel", "params": {}}),
    (_rgx(r"^(?:write|type) faster[.! ]*$"),
     lambda m: {"skill": "task.speed", "params": {"direction": "faster"}}),
    (_rgx(r"^(?:write|type) slower[.! ]*$"),
     lambda m: {"skill": "task.speed", "params": {"direction": "slower"}}),

    # --- time / date ----------------------------------------------------------
    # Keep these fully local: a simple clock question must work while the
    # conversational provider, Hermes, or the network is unavailable.
    (_rgx(r"^(?:(?:jarvis)[, ]*)?(?:(?:what(?:'s| is)|can you tell me|tell me|give me|do you know) (?:the )?(?:current )?time(?: now)?|what time is it(?: now)?|time please|current time)[.!? ]*$"),
     lambda m: {"skill": "smalltalk", "params": {"kind": "time"}}),
    (_rgx(r"^(?:(?:jarvis)[, ]*)?(?:(?:what(?:'s| is)|can you tell me|tell me) (?:the )?(?:date|day|today)|what day is (?:it|today))[.!? ]*$"),
     lambda m: {"skill": "smalltalk", "params": {"kind": "date"}}),

    # --- music ------------------------------------------------------------------
    (_rgx(r"^play (?:the )?first (?:result|video)[.! ]*$"),
     lambda m: {"skill": "browser.youtube_play_first", "params": {}}),
    (_rgx(r"^pause (?:the )?music|^pause$"),
     lambda m: {"skill": "media.control", "params": {"action": "pause"}}),
    (_rgx(r"^resume (?:the )?music|^resume$|^continue (?:the )?music"),
     lambda m: {"skill": "media.control", "params": {"action": "resume"}}),
    (_rgx(r"^next (?:video|song|track)|^skip (?:this|it)"),
     lambda m: {"skill": "media.control", "params": {"action": "next"}}),
    (_rgx(r"^mute (?:the )?music"),
     lambda m: {"skill": "media.control", "params": {"action": "mute"}}),
    (_rgx(r"^stop (?:the )?music"),
     lambda m: {"skill": "media.control", "params": {"action": "stop"}}),
    (_rgx(r"^play (?:some )?music[.! ]*$"),
     lambda m: {"skill": "media.play_music", "params": {"query": ""}}),
    (_rgx(r"^play (.+?)(?:\s+on youtube)?[.! ]*$"),
     lambda m: {"skill": "media.play_music", "params": {"query": m.group(1).strip()}}),

    # --- open / close -------------------------------------------------------------
    (_rgx(r"^close (?:it|that|this)[.! ]*$"),
     lambda m: {"skill": "app.close", "params": {"target": ""}}),
    (_rgx(r"^close everything(?: (?:jarvis|you) opened)?[.! ]*$"),
     lambda m: {"skill": "app.close", "params": {"target": "__all__"}}),
    (_rgx(r"^close (?:the )?folder[.! ]*$"),
     lambda m: {"skill": "app.close", "params": {"target": "__recent_folder__"}}),
    (_rgx(r"^close (?:the )?browser[.! ]*$"),
     lambda m: {"skill": "browser.close", "params": {"target": "browser"}}),
    (_rgx(r"^open (?:the )?browser[.! ]*$"),
     lambda m: {"skill": "browser.open", "params": {}}),
    (_rgx(r"^close (.+?)[.! ]*$"),
     lambda m: {"skill": "app.close", "params": {"target": m.group(1).strip()}}),
    (_rgx(r"^open (?:microsoft )?word and (?:create|write|make) (?:a )?(?:(short|full) )?(?:research )?report (?:about|on) (.+?)[.!?]\s*(?:create|write|make) it (?:live|visibly)(?: so i can see it)?[.!? ]*$"),
     lambda m: {"skill": "office_word.create_research_document",
                "params": {
                    "topic": m.group(2).strip(),
                    "execution_mode": "LIVE_INTERACTIVE",
                    "report_length": m.group(1) or "full",
                }}),
    (_rgx(r"^(?:create|write|make) (?:a )?(?:short |full )?(?:research )?report (?:about|on) (.+?) (?:live|visibly) in (?:microsoft )?word[.! ]*$"),
     lambda m: {"skill": "office_word.create_research_document",
                "params": {
                    "topic": m.group(1).strip(),
                    "execution_mode": "LIVE_INTERACTIVE",
                    "report_length": "short" if "short" in m.group(0).lower() else "full",
                }}),
    (_rgx(r"^(?:create|make|open) (?:a |an )?(?:new )?(?:microsoft )?word (?:document|file)[.! ]*$"),
     lambda m: {"skill": "office_word.create_document", "params": {}}),
    (_rgx(r"^(?:create|write|make) (?:a )?(?:microsoft )?word (?:document|file)(?: about| on)? (.+?)[.! ]*$"),
     lambda m: {"skill": "word.write", "params": {"topic": m.group(1).strip(), "extra": ""}}),
    (_rgx(r"^(?:create|make) (?:an? )?(?:microsoft )?excel (?:spreadsheet|file)(?: about| for| on)? (.+?)[.! ]*$"),
     lambda m: {"skill": "excel.create", "params": {"topic": m.group(1).strip()}}),
    (_rgx(r"^(?:create|make) (?:a )?(?:microsoft )?powerpoint (?:presentation|file)(?: about| on)? (.+?)[.! ]*$"),
     lambda m: {"skill": "ppt.create", "params": {"topic": m.group(1).strip()}}),
    (_rgx(r"^(?:create|write|make) (?:a )?research (?:report|document) (?:about|on) (.+?)[.! ]*$"),
     lambda m: {"skill": "research.create_report", "params": {"topic": m.group(1).strip()}}),
    (_rgx(r"^(?:find|locate|search for) (?:the )?file (.+?)[.! ]*$"),
     lambda m: {"skill": "app.search_file", "params": {"target": m.group(1).strip()}}),
    (_rgx(r"^search youtube (?:for )?(.+?)[.! ]*$|^youtube search (?:for )?(.+?)[.! ]*$"),
     lambda m: {"skill": "browser.search_youtube",
                "params": {"query": (m.group(1) or m.group(2)).strip()}}),
    (_rgx(r"^(?:open|show|go to) (?:my |the )?(desktop|downloads|documents|pictures|videos|music|home|onedrive|this pc|recycle bin|network|recent files|startup|appdata|local appdata)(?: folder| directory)?[.! ]*$"),
     lambda m: {"skill": "app.open_folder", "params": {"target": m.group(1).strip()}}),
    (_rgx(r"^open (?:my |the )?(.+?) (?:folder|directory)[.! ]*$"),
     lambda m: {"skill": "app.open_folder", "params": {"target": m.group(1).strip()}}),
    (_rgx(r"^open (?:the )?(.+?) file[.! ]*$"),
     lambda m: {"skill": "app.open_file", "params": {"target": m.group(1).strip()}}),
    (_rgx(r"^open (youtube|gmail|google|github|reddit|facebook|instagram|linkedin)[.! ]*$"),
     lambda m: {"skill": "browser.open_site", "params": {"site": m.group(1).strip()}}),
    (_rgx(r"^open whatsapp[.! ]*$"),
     lambda m: {"skill": "whatsapp.open", "params": {}}),
    (_rgx(r"^open (?:microsoft )?(word|excel|powerpoint|outlook|onenote)[.! ]*$"),
     lambda m: {"skill": "app.open", "params": {"target": m.group(1).strip()}}),
    (_rgx(r"^open (notepad|calculator|paint|task manager|command prompt|powershell|terminal|file explorer|settings|snipping tool|media player)[.! ]*$"),
     lambda m: {"skill": "app.open", "params": {"target": m.group(1).strip()}}),
    # --- window control (front/min/max/restore/focus/switch) ----------------------
    (_rgx(r"^(?:bring|switch) (?:to )?(?:the )?(.+?) (?:to (?:the )?front|up)[.! ]*$"),
     lambda m: {"skill": "window.front", "params": {"target": m.group(1).strip()}}),
    (_rgx(r"^minimize (?:the )?(.+?)[.! ]*$"),
     lambda m: {"skill": "window.minimize", "params": {"target": m.group(1).strip()}}),
    (_rgx(r"^maximize (?:the )?(.+?)[.! ]*$"),
     lambda m: {"skill": "window.maximize", "params": {"target": m.group(1).strip()}}),
    (_rgx(r"^restore (?:the )?(.+?)[.! ]*$"),
     lambda m: {"skill": "window.restore", "params": {"target": m.group(1).strip()}}),
    (_rgx(r"^(?:focus|switch to) (?:the )?(.+?)[.! ]*$"),
     lambda m: {"skill": "window.focus", "params": {"target": m.group(1).strip()}}),
    (_rgx(r"^open (.+?)[.! ]*$"),
     lambda m: {"skill": "app.open", "params": {"target": m.group(1).strip()}}),

    # --- email ----------------------------------------------------------------------
    (_rgx(r"^(?:check|pull up|open) (?:my )?(?:email|emails|inbox|gmail)"),
     lambda m: {"skill": "email.check", "params": {}}),

    # --- news -----------------------------------------------------------------------
    (_rgx(r"^(?:what(?:'s| is) the )?(?:latest )?news$|^read me the news|^news update|^top headlines"),
     lambda m: {"skill": "news.latest", "params": {}}),
    (_rgx(r"^news about (.+)$|^(.+?) news$"),
     lambda m: {"skill": "news.topic",
                "params": {"topic": (m.group(1) or m.group(2) or "").strip()}}),

    # --- desktop organizer -------------------------------------------------------------
    (_rgx(r"^organize (?:my )?desktop|^clean (?:up )?my desktop|^tidy (?:up )?my desktop"),
     lambda m: {"skill": "desktop.organize", "params": {}}),
    (_rgx(r"^undo (?:the )?organiz"),
     lambda m: {"skill": "desktop.undo", "params": {}}),

    # --- web search -----------------------------------------------------------------------
    (_rgx(r"^search google (?:for )?(.+?)[.! ]*$"),
     lambda m: {"skill": "web.search", "params": {"query": m.group(1).strip()}}),
    (_rgx(r"^(?:google|search for|search|look up) (.+)$"),
     lambda m: {"skill": "web.search", "params": {"query": m.group(1).strip()}}),

    # --- memory --------------------------------------------------------------------------------
    (_rgx(r"^remember (?:that )?(.+)$"),
     lambda m: {"skill": "chat",
                "params": {"message": m.group(0), "remember": m.group(1).strip()}}),

    # --- smalltalk -------------------------------------------------------------------------------
    (_rgx(r"^(?:hello|hi|hey|good morning|good afternoon|good evening)(?: jarvis)?[.! ]*$"),
     lambda m: {"skill": "smalltalk", "params": {"kind": "greeting"}}),
    (_rgx(r"^(?:thank you|thanks|thanks a lot|cheers)(?: jarvis)?[.! ]*$"),
     lambda m: {"skill": "smalltalk", "params": {"kind": "thanks"}}),
    (_rgx(r"^how are you(?: doing)?[.!? ]*$"),
     lambda m: {"skill": "smalltalk", "params": {"kind": "howareyou"}}),
    (_rgx(r"^(?:good ?bye|goodnight|good night|see you|that(?:'s| is) all)(?: jarvis)?[.! ]*$"),
     lambda m: {"skill": "smalltalk", "params": {"kind": "goodbye"}}),
]


def fast_lane(text):
    """Return an intent dict instantly, or None to fall through to the LLM router."""
    t = (text or "").strip()
    if not t:
        return None
    # Browser navigation must be decided before the generic "open X" / "search
    # X" rules below.  Otherwise flexible requests such as "open Google and
    # look up local LLM education" become an application launch and can fall
    # through to a cloud planner.
    try:
        from core.automation_intents import classify_browser_intent
        browser_intent = classify_browser_intent(t)
        if browser_intent is not None:
            return browser_intent
    except Exception:
        pass
    for pattern, builder in FAST_RULES:
        m = pattern.search(t)
        if m:
            try:
                return builder(m)
            except Exception:
                return None
    try:
        from core.automation_intents import classify_automation_intent
        return classify_automation_intent(t)
    except Exception:
        return None


# ==========================================================================
# 2. ROUTER BRAIN â€” local Qwen2.5-0.5B-Instruct
# ==========================================================================
VALID_SKILLS = {
    "app.open", "app.open_app", "app.open_file", "app.open_folder", "app.search_file", "app.close", "system.volume", "system.screenshot", "system.lock",
    "system.shutdown", "system.status", "media.play_music", "media.control",
    "browser.open", "browser.open_site", "browser.search_youtube", "browser.search_youtube_and_play", "browser.close", "web.search", "news.latest",
    "news.topic", "news.more", "news.save", "email.check", "email.read",
    "email.compose", "email.reply", "whatsapp.open", "whatsapp.read",
    "whatsapp.reply", "word.write", "word.continue", "office_word.create_document",
    "office_word.create_research_document", "task.pause", "task.resume", "task.cancel", "task.speed", "excel.create",
    "excel.read", "ppt.create", "desktop.organize", "desktop.undo",
    "codex.build", "research.start", "research.create_report", "research.prepare_report",
    "research.gather_report", "research.draft_report", "research.finalize_report",
    "research.open_report", "research.continue", "research.finalize",
    "research.outline", "chat", "smalltalk",
    "window.front", "window.minimize", "window.maximize", "window.restore", "window.focus", "window.close",
    "system.emergency_stop", "office.create_document", "office.create_spreadsheet",
    "office.create_presentation", "office.save", "office.export",
    "browser.back", "browser.forward", "browser.new_tab", "browser.close_tab",
    "browser.switch_tab", "browser.read_page", "browser.find_on_page",
    "browser.fill_form", "browser.submit_form", "browser.download",
    "browser.upload", "browser.youtube_play_first", "browser.youtube_play_relevant", "browser.play_video",
    "browser.pause_video",
    "website.gmail_search", "website.gmail_open_latest",
    "website.gmail_reply_draft", "website.drive_search",
    "website.drive_show_location", "website.stripe_search_payment",
}


class Router:
    """Lazy-loaded local classifier. First classify() pays the model load."""

    def __init__(self, model_name=None):
        self.model_name = model_name or Config.ROUTER_MODEL_NAME
        self._model = None
        self._tokenizer = None
        self._load_lock = threading.Lock()
        self.load_error = ""

    # ---------------------------------------------------------------- load
    def preload(self):
        """Call from a background thread at startup so first command is fast."""
        self._ensure_loaded()

    def _ensure_loaded(self):
        if self._model is not None:
            return True
        # Skip local router when disabled (packaged mode default)
        if not Config.LOCAL_ROUTER_ENABLED:
            self.load_error = "Local router is disabled (LOCAL_ROUTER_ENABLED=false)"
            return False
        with self._load_lock:
            if self._model is not None:
                return True
            try:
                try:
                    import torch
                    from transformers import AutoModelForCausalLM, AutoTokenizer
                except ImportError:
                    from config import activate_external_runtime
                    if not activate_external_runtime():
                        raise
                    for module_name in list(sys.modules):
                        if module_name == "torch" or module_name.startswith("torch."):
                            sys.modules.pop(module_name, None)
                        elif module_name == "transformers" or module_name.startswith("transformers."):
                            sys.modules.pop(module_name, None)
                    importlib.invalidate_caches()
                    import torch
                    from transformers import AutoModelForCausalLM, AutoTokenizer
                self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self._model = AutoModelForCausalLM.from_pretrained(
                    self.model_name,
                    torch_dtype="auto",
                    device_map="auto",
                    low_cpu_mem_usage=True,
                )
                self._model.eval()
                self._torch = torch
                return True
            except Exception as exc:
                if os.getenv('JARVIS_ROUTER_DEBUG') == '1':
                    traceback.print_exc()
                self.load_error = str(exc)
                self._model = None
                return False

    # ------------------------------------------------------------ classify
    def classify(self, text):
        """Return {"skill": ..., "params": {...}}. Falls back to chat on any failure."""
        fallback = {"skill": "chat", "params": {"message": text}}
        if not self._ensure_loaded():
            return fallback
        try:
            messages = [
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ]
            prompt = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self._tokenizer([prompt], return_tensors="pt")
            inputs = {k: v.to(self._model.device) for k, v in inputs.items()}
            with self._torch.no_grad():
                out = self._model.generate(
                    **inputs,
                    max_new_tokens=Config.ROUTER_MAX_NEW_TOKENS,
                    do_sample=False,
                    temperature=None,
                    top_p=None,
                    top_k=None,
                    pad_token_id=self._tokenizer.eos_token_id,
                )
            gen = out[0][inputs["input_ids"].shape[-1]:]
            text_out = self._tokenizer.decode(gen, skip_special_tokens=True).strip()
            intent = self._parse_json(text_out)
            if not intent:
                return fallback
            skill = str(intent.get("skill", "")).strip()
            if skill not in VALID_SKILLS:
                return fallback
            params = intent.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            if skill == "chat" and "message" not in params:
                params["message"] = text
            return {"skill": skill, "params": params}
        except Exception:
            return fallback

    @staticmethod
    def _parse_json(text):
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            try:
                fixed = re.sub(r",(\s*[}\]])", r"\1", match.group(0))
                return json.loads(fixed)
            except Exception:
                return None
