"""Human conversation mode state, settings, and lightweight intent routing."""
from __future__ import annotations

import dataclasses
import re
import threading
import time
import uuid
from typing import Any

from core.command_text import cleanup_command

SLEEPING = "SLEEPING"
WAKE_WORD_DETECTED = "WAKE_WORD_DETECTED"
LISTENING = "LISTENING"
TRANSCRIBING = "TRANSCRIBING"
THINKING = "THINKING"
SPEAKING = "SPEAKING"
CONVERSATION_LISTENING = "CONVERSATION_LISTENING"
EXECUTING_TOOL = "EXECUTING_TOOL"
WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
INTERRUPTED = "INTERRUPTED"
ENDING_CONVERSATION = "ENDING_CONVERSATION"
ERROR_RECOVERY = "ERROR_RECOVERY"

INTENT_CONVERSATION = "conversation"
INTENT_QUESTION = "question"
INTENT_COMPUTER_COMMAND = "computer_command"
INTENT_WEB_TASK = "web_task"
INTENT_APPLICATION_TASK = "application_task"
INTENT_FILE_TASK = "file_task"
INTENT_FOLLOW_UP = "follow_up_response"
INTENT_CORRECTION = "correction"
INTENT_EXIT = "exit_request"

DEFAULT_EXIT_PHRASES = (
    "stop listening",
    "end conversation",
    "that is all",
    "that's all",
    "go to sleep",
    "goodbye jarvis",
    "good bye jarvis",
    "exit conversation mode",
    "thank you jarvis that is all",
    "thanks jarvis that is all",
    "never mind",
    "cancel",
)


@dataclasses.dataclass
class ConversationSettings:
    enabled: bool = True
    follow_up_listening: bool = True
    barge_in: bool = False
    first_silence_reminder_seconds: float = 15.0
    second_silence_reminder_seconds: float = 30.0
    inactivity_timeout_seconds: float = 60.0
    silence_detection_seconds: float = 1.4
    speech_start_threshold: int = 3
    minimum_speech_seconds: float = 0.35
    maximum_recording_seconds: float = 30.0
    post_speech_delay_seconds: float = 0.35
    background_noise_threshold: float = 0.015
    response_length: str = "concise"
    memory_limit: int = 20
    return_to_wake_after_inactivity: bool = True
    exit_phrases: tuple[str, ...] = DEFAULT_EXIT_PHRASES
    microphone_sensitivity: float = 1.0
    echo_suppression: bool = True
    background_noise_filtering: bool = True

    @classmethod
    def from_store(cls, store: Any) -> "ConversationSettings":
        if store is None:
            return cls()

        def get(key, default):
            try:
                return store.get(key, default)
            except Exception:
                return default

        return cls(
            enabled=bool(get("conversation_mode_enabled", True)),
            follow_up_listening=bool(get("followup_listening_enabled", True)),
            barge_in=bool(get("barge_in_enabled", False)),
            first_silence_reminder_seconds=_float(
                get("silence_reminder_seconds", 15.0), 15.0, 1.0, 3600.0,
            ),
            second_silence_reminder_seconds=_float(
                get("second_silence_reminder_seconds", 30.0), 30.0, 1.0, 3600.0,
            ),
            inactivity_timeout_seconds=_float(
                get("conversation_inactivity_timeout_seconds", 60.0),
                60.0, 5.0, 7200.0,
            ),
            silence_detection_seconds=_float(
                get("silence_detection_seconds", 1.4), 1.4, 0.3, 5.0,
            ),
            speech_start_threshold=max(
                1, min(12, int(_float(get("speech_start_threshold", 3), 3, 1, 12))),
            ),
            minimum_speech_seconds=_float(
                get("minimum_speech_seconds", 0.35), 0.35, 0.0, 5.0,
            ),
            maximum_recording_seconds=_float(
                get("maximum_recording_seconds", 30.0), 30.0, 3.0, 300.0,
            ),
            post_speech_delay_seconds=_float(
                get("post_speech_listening_delay_seconds", 0.35), 0.35, 0.0, 5.0,
            ),
            background_noise_threshold=_float(
                get("background_noise_threshold", 0.015), 0.015, 0.0, 1.0,
            ),
            response_length=str(get("conversation_response_length", "concise") or "concise"),
            memory_limit=max(
                4, min(100, int(_float(get("conversation_memory_limit", 20), 20, 4, 100))),
            ),
            return_to_wake_after_inactivity=bool(
                get("return_to_wake_after_inactivity", True),
            ),
            exit_phrases=_parse_exit_phrases(
                get("conversation_exit_phrases", "\n".join(DEFAULT_EXIT_PHRASES)),
            ),
            microphone_sensitivity=_float(
                get("microphone_sensitivity", 1.0), 1.0, 0.1, 5.0,
            ),
            echo_suppression=bool(get("echo_suppression_enabled", True)),
            background_noise_filtering=bool(
                get("background_noise_filtering_enabled", True),
            ),
        )


def _float(value, default, minimum, maximum):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    return max(float(minimum), min(float(maximum), parsed))


def _parse_exit_phrases(value):
    if isinstance(value, (list, tuple)):
        phrases = value
    else:
        phrases = re.split(r"[\n,]+", str(value or ""))
    cleaned = tuple(
        " ".join(str(phrase).lower().split()).strip(" .!?")
        for phrase in phrases
        if str(phrase).strip()
    )
    return cleaned or DEFAULT_EXIT_PHRASES


@dataclasses.dataclass
class ConversationSession:
    session_id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex)
    start_time: float = dataclasses.field(default_factory=time.time)
    last_activity_time: float = dataclasses.field(default_factory=time.time)
    active: bool = False
    message_history: list[dict[str, str]] = dataclasses.field(default_factory=list)
    current_topic: str = ""
    current_task: str = ""
    pending_question: str = ""
    pending_confirmation: str = ""
    tool_execution_results: list[dict[str, str]] = dataclasses.field(default_factory=list)
    user_interruption_state: str = ""
    summary: str = ""


@dataclasses.dataclass
class ConversationIntent:
    intent_type: str
    cleaned_text: str
    route: dict[str, Any] | None = None

    @property
    def uses_tools(self) -> bool:
        return self.intent_type in {
            INTENT_COMPUTER_COMMAND,
            INTENT_WEB_TASK,
            INTENT_APPLICATION_TASK,
            INTENT_FILE_TASK,
        }


class ConversationManager:
    def __init__(self, settings: ConversationSettings | None = None):
        self._lock = threading.RLock()
        self.settings = settings or ConversationSettings()
        self.session = ConversationSession()
        self.state = SLEEPING

    def configure(self, store=None, settings: ConversationSettings | None = None):
        with self._lock:
            self.settings = settings or ConversationSettings.from_store(store)
        return self.settings

    @property
    def active(self):
        with self._lock:
            return bool(self.session.active)

    def begin(self, *, user_text="", current_task=""):
        with self._lock:
            if not self.session.active:
                self.session = ConversationSession(active=True)
            self.session.active = True
            self.session.current_task = current_task or self.session.current_task
            self.session.last_activity_time = time.time()
            self.state = CONVERSATION_LISTENING
            if user_text:
                self.record_user(user_text)
            return self.snapshot()

    def end(self, reason=""):
        with self._lock:
            self.session.active = False
            self.session.pending_question = ""
            self.session.pending_confirmation = ""
            self.state = ENDING_CONVERSATION if reason else SLEEPING
            return self.snapshot()

    def set_state(self, state):
        with self._lock:
            self.state = str(state or SLEEPING)
            return self.state

    def mark_interrupted(self):
        with self._lock:
            self.session.user_interruption_state = "interrupted"
            self.session.last_activity_time = time.time()
            self.state = INTERRUPTED

    def record_user(self, text):
        self._record("user", text)

    def record_assistant(self, text):
        self._record("assistant", text)
        cleaned = str(text or "").strip()
        if cleaned.endswith("?"):
            with self._lock:
                self.session.pending_question = cleaned

    def record_tool_result(self, command, result):
        with self._lock:
            self.session.tool_execution_results.append({
                "command": str(command or ""),
                "result": str(result or ""),
            })
            self.session.tool_execution_results = self.session.tool_execution_results[-20:]
            self.session.last_activity_time = time.time()

    def _record(self, role, text):
        cleaned = str(text or "").strip()
        if not cleaned:
            return
        with self._lock:
            self.session.message_history.append({"role": role, "content": cleaned})
            self.session.last_activity_time = time.time()
            if role == "user":
                self.session.pending_question = ""
                self.session.current_topic = _topic_hint(cleaned) or self.session.current_topic
            self._trim_history_locked()

    def _trim_history_locked(self):
        limit = max(4, int(self.settings.memory_limit)) * 2
        if len(self.session.message_history) <= limit:
            return
        overflow = self.session.message_history[:-limit]
        self.session.message_history = self.session.message_history[-limit:]
        first = overflow[0]["content"][:80] if overflow else ""
        last = overflow[-1]["content"][:80] if overflow else ""
        self.session.summary = (
            f"{len(overflow)} older messages summarized. "
            f"Earlier topic began with: {first}. Recent older point: {last}."
        )

    def is_exit_request(self, text):
        cleaned = _normalize(text)
        if not cleaned:
            return False
        return any(cleaned == phrase or cleaned.endswith(" " + phrase)
                   for phrase in self.settings.exit_phrases)

    def classify(self, text, ctx=None):
        cleaned = cleanup_command(text)
        if not cleaned:
            return ConversationIntent(INTENT_CONVERSATION, "")
        if self.is_exit_request(cleaned):
            return ConversationIntent(INTENT_EXIT, cleaned)

        low = cleaned.lower()
        if re.search(r"\b(no|actually|i mean|correction|that's not|that is not)\b", low):
            return ConversationIntent(INTENT_CORRECTION, cleaned)

        pending = getattr(ctx, "pending", None) if ctx is not None else None
        if pending is not None:
            return ConversationIntent(
                INTENT_FOLLOW_UP,
                cleaned,
                {"route_type": "pending", "selected_engine": "contextual_pending"},
            )

        route = self._deterministic_route(cleaned, ctx)
        if route is not None:
            skill = str((route.get("intent") or {}).get("skill") or "")
            return ConversationIntent(_intent_type_for_skill(skill), cleaned, route)

        with self._lock:
            pending_question = self.session.pending_question
            current_task = self.session.current_task
        if pending_question and _looks_like_short_answer(cleaned):
            return ConversationIntent(INTENT_FOLLOW_UP, cleaned)
        if current_task and _looks_like_short_answer(cleaned):
            return ConversationIntent(INTENT_FOLLOW_UP, cleaned)
        if "?" in cleaned or low.startswith(("what ", "why ", "how ", "when ", "where ", "who ")):
            return ConversationIntent(INTENT_QUESTION, cleaned)
        return ConversationIntent(INTENT_CONVERSATION, cleaned)

    def _deterministic_route(self, cleaned, ctx):
        state = getattr(ctx, "state", {}) if ctx is not None else {}
        try:
            from brain.router import fast_lane
            intent = fast_lane(cleaned, state)
        except Exception:
            intent = None
        if intent is not None and str(intent.get("skill") or "") not in {"chat", "smalltalk"}:
            return {
                "route_type": "intent",
                "selected_engine": "deterministic",
                "intent": intent,
                "plan": [],
            }
        try:
            from core.planner import plan_command
            plan = plan_command(cleaned)
        except Exception:
            plan = []
        if plan:
            return {
                "route_type": "plan",
                "selected_engine": "deterministic_planner",
                "intent": None,
                "plan": plan,
            }
        return None

    def snapshot(self):
        with self._lock:
            session = self.session
            return {
                "conversation_active": session.active,
                "conversation_state": self.state,
                "conversation_session_id": session.session_id if session.active else "",
                "conversation_started_at": session.start_time if session.active else 0.0,
                "conversation_last_activity": session.last_activity_time,
                "conversation_turns": len(session.message_history),
                "conversation_topic": session.current_topic,
                "conversation_task": session.current_task,
                "conversation_pending_question": session.pending_question,
                "conversation_pending_confirmation": session.pending_confirmation,
                "conversation_interrupted": session.user_interruption_state == "interrupted",
                "conversation_summary": session.summary,
            }

    def messages_for_model(self):
        with self._lock:
            return list(self.session.message_history), self.session.summary


def _normalize(text):
    return " ".join(str(text or "").lower().split()).strip(" .!?")


def _looks_like_short_answer(text):
    words = re.findall(r"[A-Za-z0-9']+", str(text or ""))
    return 0 < len(words) <= 8


def _intent_type_for_skill(skill):
    if skill.startswith(("browser.", "web.", "website.")):
        return INTENT_WEB_TASK
    if skill.startswith(("app.", "window.", "office", "word.", "excel.", "ppt.")):
        return INTENT_APPLICATION_TASK
    if skill.startswith(("desktop.", "file.")) or skill in {"app.open_file", "app.search_file"}:
        return INTENT_FILE_TASK
    return INTENT_COMPUTER_COMMAND


def _topic_hint(text):
    match = re.search(r"\b(?:about|regarding|on)\s+(.+)$", str(text or ""), re.I)
    if match:
        return match.group(1).strip(" .!?")[:120]
    return ""
