"""
WhatsApp Desktop — UI automation via pywinauto + pyautogui + pyperclip.

Opens the UWP app, finds chats by contact name, reads visible messages,
types and sends replies. Every outbound message requires voice
confirmation unless AUTO_SEND=true in .env.

UI automation is inherently best-effort: the module retries, degrades
gracefully, and always tells you what happened out loud.
"""
import subprocess
import time

from config import Config
from brain.prompts import WHATSAPP_DRAFT_PROMPT

APP_URI = r"shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"


# ===========================================================================
# App control
# ===========================================================================
def open_app(ctx):
    """Launch WhatsApp Desktop and register it."""
    try:
        import os
        os.startfile("whatsapp:")
    except Exception:
        try:
            subprocess.Popen(["explorer.exe", APP_URI], shell=False)
        except Exception as exc:
            return f"I couldn't launch WhatsApp, sir: {exc}."
    ctx.registry.register("app", "WhatsApp", window_title="WhatsApp")
    return "Opening WhatsApp, sir."


def _connect_window(timeout=20):
    """Attach to the WhatsApp window. Returns a pywinauto WindowSpecification."""
    from pywinauto import Desktop
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            win = Desktop(backend="uia").window(title_re=".*WhatsApp.*")
            if win.exists(timeout=2):
                win.set_focus()
                return win
        except Exception:
            time.sleep(1)
    return None


def _find_edits(win):
    try:
        return [e for e in win.descendants(control_type="Edit") if e.is_visible()]
    except Exception:
        return []


def open_chat(contact, ctx, retries=3):
    """Open the chat with the named contact. Returns the window or None."""
    contact = (contact or "").strip()
    if not contact:
        return None
    for attempt in range(retries):
        win = _connect_window()
        if win is None:
            time.sleep(2)
            continue
        try:
            edits = _find_edits(win)
            if not edits:
                time.sleep(1.5)
                continue
            search = edits[0]                     # search box is the first Edit
            search.click_input()
            time.sleep(0.4)
            _paste_text(contact)
            time.sleep(1.8)                       # let results populate
            import pyautogui
            pyautogui.press("enter")
            time.sleep(1.2)
            return win
        except Exception:
            time.sleep(1.5)
    return None


def _paste_text(text):
    import pyperclip
    import pyautogui
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)


def read_visible_messages(win, limit=15):
    """Best-effort extraction of visible message texts from the open chat."""
    texts = []
    try:
        for item in win.descendants(control_type="ListItem"):
            try:
                t = (item.window_text() or "").strip()
                if not t:
                    t = " ".join(
                        (c.window_text() or "").strip()
                        for c in item.descendants(control_type="Text")
                    ).strip()
                if t and t not in texts:
                    texts.append(t)
            except Exception:
                continue
    except Exception:
        pass
    return texts[-limit:] if texts else []


def send_text(text):
    """Type into the message box of the open chat and press Enter."""
    import pyautogui
    win = _connect_window(timeout=8)
    if win is None:
        return False
    try:
        edits = _find_edits(win)
        box = edits[-1] if edits else None       # message box is the last Edit
        if box is not None:
            box.click_input()
            time.sleep(0.3)
        _paste_text(text)
        time.sleep(0.3)
        pyautogui.press("enter")
        time.sleep(0.6)
        return True
    except Exception:
        return False


# ===========================================================================
# Actions
# ===========================================================================
def read_chat(contact, ctx):
    contact = (contact or "").strip()
    # A general "check my WhatsApp messages" request means the currently
    # visible conversation. Never search the official client for an empty
    # contact or invent a contact name.
    win = open_chat(contact, ctx) if contact else _connect_window()
    if win is None:
        if not contact:
            return "I couldn't find the WhatsApp Desktop window, sir."
        return (f"I couldn't find the chat with {contact}, sir. "
                f"Is that the exact contact name?")
    msgs = read_visible_messages(win, limit=10)
    if contact:
        ctx.state["whatsapp_contact"] = contact
    if msgs:
        ctx.state["whatsapp_last"] = msgs[-1]
    if not msgs and not contact:
        return ("The visible WhatsApp conversation is open, sir, but I "
                "couldn't read its messages. WhatsApp's UI may be obscured.")
    if not msgs:
        return (f"The chat with {contact} is open, sir, but I couldn't "
                f"read its messages — WhatsApp's UI may be obscured.")
    lines = [
        f"Latest messages with {contact}, sir:"
        if contact else "Latest visible WhatsApp messages, sir:"
    ]
    for m in msgs[-5:]:
        lines.append(m.replace("\n", " ")[:160])
    return " ".join(lines)


def reply_to(contact, message, ctx):
    contact = (contact or ctx.state.get("whatsapp_contact") or "").strip()
    if not contact:
        return "Reply to whom, sir?"

    win = open_chat(contact, ctx)
    if win is None:
        return f"I couldn't open the chat with {contact}, sir."

    draft = (message or "").strip()
    if not draft:
        last_msgs = read_visible_messages(win, limit=10)
        last = last_msgs[-1] if last_msgs else ""
        if not last:
            return (f"The chat with {contact} is open but I can't see any "
                    f"message to reply to, sir.")
        draft = ctx.llm.quick(
            WHATSAPP_DRAFT_PROMPT.format(contact=contact, message=last[:800]),
            max_tokens=200,
        ) if ctx.llm.available else ""
        if not draft:
            return "My drafting service is unavailable, sir."

    def _send():
        if send_text(draft):
            return f"Replied to {contact}, sir."
        return f"I couldn't deliver the message to {contact}, sir."

    if Config.AUTO_SEND or not Config.CONFIRM_SENDS:
        return _send()

    ctx.speaker.speak(f"For {contact}, I have: {draft}. Send it? Say yes or no.")
    ctx.pending = {
        "kind": "confirm",
        "prompt": f"WhatsApp reply to {contact}",
        "on_yes": _send,
        "on_no": lambda: "Discarded, sir.",
    }
    return None


def reply_all_unread(ctx):
    """Best-effort pass over chats that show unread badges."""
    win = _connect_window()
    if win is None:
        return "WhatsApp isn't open, sir."
    replied, skipped = 0, 0
    try:
        chats = win.descendants(control_type="ListItem")
    except Exception:
        chats = []
    for chat in chats[:12]:
        try:
            name = (chat.window_text() or "").strip().split("\n")[0]
            if not name:
                continue
            # an unread chat usually shows a count badge as a Text child
            has_unread = any(
                (c.window_text() or "").strip().isdigit()
                for c in chat.descendants(control_type="Text")
            )
            if not has_unread:
                continue
            chat.click_input()
            time.sleep(1.2)
            msgs = read_visible_messages(win, limit=10)
            if not msgs:
                skipped += 1
                continue
            draft = ctx.llm.quick(
                WHATSAPP_DRAFT_PROMPT.format(contact=name, message=msgs[-1][:800]),
                max_tokens=200,
            ) if ctx.llm.available else ""
            if not draft:
                skipped += 1
                continue
            if Config.AUTO_SEND or not Config.CONFIRM_SENDS:
                if send_text(draft):
                    replied += 1
                else:
                    skipped += 1
            else:
                ctx.speaker.speak(
                    f"Unread from {name}: {msgs[-1][:120]}. "
                    f"My reply: {draft}. Send it?")
                answer = ctx.listener.listen(max_seconds=8).lower()
                if any(w in answer for w in ("yes", "yeah", "send", "sure", "go")):
                    if send_text(draft):
                        replied += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception:
            skipped += 1
            continue
    if replied == 0 and skipped == 0:
        return "I don't see any unread chats, sir."
    return f"Replied to {replied} chat{'s' if replied != 1 else ''}, sir, and skipped {skipped}."


# ===========================================================================
# Skill dispatch entry
# ===========================================================================
def handle(intent, ctx):
    skill = intent.get("skill")
    params = intent.get("params", {}) or {}
    if skill == "whatsapp.open":
        return open_app(ctx)
    if skill == "whatsapp.read":
        return read_chat(params.get("contact", ""), ctx)
    if skill == "whatsapp.reply":
        contact = (params.get("contact") or "").strip()
        if not contact or contact.lower() in ("all", "everyone", "all unread"):
            return reply_all_unread(ctx)
        return reply_to(contact, params.get("message", ""), ctx)
    return None
