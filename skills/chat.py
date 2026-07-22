"""
Conversation & Memory — free discussion with short-term context
(last ~20 exchanges) plus a persistent memory.json for facts about you
("remember that I prefer tea"). Smalltalk is instant and model-free.
"""
import json
import time
from collections import deque
from datetime import datetime

from config import Config
from brain.prompts import JARVIS_SYSTEM_PROMPT

_history = deque(maxlen=Config.CHAT_HISTORY_TURNS * 2)


# ---------------------------------------------------------------------------
# Persistent memory
# ---------------------------------------------------------------------------
def _load_memory():
    try:
        if Config.MEMORY_FILE.exists():
            data = json.loads(Config.MEMORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("facts", [])
                return data
    except Exception:
        pass
    return {"facts": []}


def _save_memory(data):
    try:
        Config.MEMORY_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def remember(fact, ctx):
    fact = (fact or "").strip()
    if not fact:
        return "Remember what, sir?"
    data = _load_memory()
    if fact.lower() not in [f.lower() for f in data["facts"]]:
        data["facts"].append(fact)
        _save_memory(data)
    return f"Noted, sir. I'll remember that {fact}."


def _memory_block():
    facts = _load_memory().get("facts", [])
    if not facts:
        return "(none yet)"
    return "\n".join(f"- {f}" for f in facts[-30:])


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------
def chat(message, remember_fact, ctx):
    if remember_fact:
        return remember(remember_fact, ctx)

    message = (message or "").strip()
    if not message:
        return "Yes, sir?"

    # Clock, date and a small set of conversational courtesies deliberately
    # stay local.  They should remain available even if the OpenRouter model
    # is offline or configured only for guarded planning.
    local_reply = _local_conversation_reply(message, ctx)
    if local_reply:
        _remember_exchange(message, local_reply)
        return local_reply

    if not ctx.llm.available:
        reply = _offline_reply(message)
        _remember_exchange(message, reply)
        return reply

    system = JARVIS_SYSTEM_PROMPT.format(
        address=Config.OWNER_ADDRESS, memory=_memory_block())
    messages = [{"role": "system", "content": system}]
    messages.extend(list(_history))
    messages.append({"role": "user", "content": message})

    reply = ctx.llm.chat(messages, temperature=0.75, max_tokens=450)
    if not reply:
        reply = _offline_reply(message)

    _remember_exchange(message, reply)
    return reply


def _remember_exchange(message, reply):
    """Keep a bounded conversational context without writing chat text to disk."""
    _history.append({"role": "user", "content": str(message)})
    _history.append({"role": "assistant", "content": str(reply)})


def _local_clock():
    """Return the local Windows clock with its configured timezone label."""
    now = datetime.now().astimezone()
    zone = now.tzname() or "local time"
    return now, zone


def _format_clock_time(now):
    """Format a 12-hour clock without platform-specific ``strftime`` flags."""
    hour = now.hour % 12 or 12
    return f"{hour}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"


def _local_conversation_reply(message, ctx):
    """Answer deterministic everyday conversation without a provider call."""
    low = " ".join(str(message).lower().split()).strip(" .!?")
    address = Config.OWNER_ADDRESS
    time_phrases = (
        "what time is it", "what is the time", "what's the time",
        "tell me the time", "current time", "time please", "time now",
        "can you tell me the time", "give me the time", "do you know the time",
    )
    date_phrases = (
        "what is the date", "what's the date", "what day is it",
        "what day is today", "tell me the date", "what is today",
    )
    if any(phrase in low for phrase in time_phrases):
        now, zone = _local_clock()
        return f"It is {_format_clock_time(now)} {zone}, {address}."
    if any(phrase in low for phrase in date_phrases):
        now, _ = _local_clock()
        return f"Today is {now.strftime('%A, %d %B %Y')}, {address}."
    if low in {"who are you", "what are you"}:
        return f"I'm JARVIS, your desktop assistant, {address}."
    if low in {"what can we talk about", "can we talk", "let's talk", "lets talk"}:
        return (f"Of course, {address}. We can talk through ideas, plan work, "
                "or simply have a conversation.")
    return ""


def _offline_reply(message):
    """Useful local response when OpenRouter is unavailable."""
    low = message.lower()
    if any(word in low for word in ("help", "what can you do", "capabilities")):
        return (
            "Cloud reasoning is offline, sir, but local controls remain available: "
            "apps, files, music, browser, volume, power, news feeds, and Office tasks."
        )
    if "who are you" in low:
        return "I'm JARVIS, your local Windows assistant, currently in offline mode, sir."
    return (
        "The cloud reasoning service is unavailable, sir. Local commands still work; "
        "conversation, drafting, and summarization will resume when the connection returns."
    )


# ---------------------------------------------------------------------------
# Smalltalk — instant, zero model calls
# ---------------------------------------------------------------------------
def smalltalk(kind, ctx):
    a = Config.OWNER_ADDRESS
    kind = (kind or "").lower()
    if kind == "greeting":
        hour = time.localtime().tm_hour
        daypart = ("morning" if hour < 12 else
                   "afternoon" if hour < 18 else "evening")
        return f"Good {daypart}, {a}. How may I assist?"
    if kind == "thanks":
        return f"You're welcome, {a}."
    if kind == "howareyou":
        return f"All systems running smoothly, {a} — thank you for asking. And you?"
    if kind == "goodbye":
        return f"Very good, {a}. I'll be here when you need me."
    if kind == "time":
        now, zone = _local_clock()
        return f"It is {_format_clock_time(now)} {zone}, {a}."
    if kind == "date":
        return f"Today is {time.strftime('%A, %d %B %Y')}, {a}."
    return f"Yes, {a}?"


# ---------------------------------------------------------------------------
# Skill dispatch entry
# ---------------------------------------------------------------------------
def handle(intent, ctx):
    skill = intent.get("skill")
    params = intent.get("params", {}) or {}
    if skill == "chat":
        return chat(params.get("message", ""), params.get("remember", ""), ctx)
    if skill == "smalltalk":
        return smalltalk(params.get("kind", ""), ctx)
    return None
