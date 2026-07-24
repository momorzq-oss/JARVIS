"""
Authoritative voice state - the single source of truth for the whole GUI.

MainWindow, tray, workers and the controller all render ONLY from this
object. No duplicate mic/speaker booleans anywhere else.
"""
import threading


class VoiceState:
    def __init__(self):
        self._lock = threading.RLock()
        # microphone
        self.microphone_available = False
        self.microphone_active = False
        self.selected_microphone = ""
        # speaker
        self.speaker_available = False
        self.speaker_engine = ""        # "Piper" | ""
        self.speaker_state = "unavailable"  # unavailable|ready|speaking|muted|error
        # wake word
        self.wakeword_loaded = False
        self.wakeword_active = False
        self.wakeword_score = 0.0
        self.wakeword_max_score = 0.0
        self.wakeword_threshold = 0.5
        # whisper / pipeline
        self.whisper_loaded = False
        self.recording = False
        self.processing = False
        # human conversation mode
        self.conversation_active = False
        self.conversation_state = "SLEEPING"
        self.conversation_session_id = ""
        self.conversation_started_at = 0.0
        self.conversation_last_activity = 0.0
        self.conversation_turns = 0
        self.conversation_topic = ""
        self.conversation_task = ""
        self.conversation_pending_question = ""
        self.conversation_pending_confirmation = ""
        self.conversation_interrupted = False
        self.conversation_summary = ""
        self.waiting_for_reply = False
        # diagnostics
        self.input_level = 0.0
        self.frames_per_second = 0.0
        self.last_audio_error = ""

    def snapshot(self):
        with self._lock:
            return {
                "microphone_available": self.microphone_available,
                "microphone_active": self.microphone_active,
                "selected_microphone": self.selected_microphone,
                "speaker_available": self.speaker_available,
                "speaker_engine": self.speaker_engine,
                "speaker_state": self.speaker_state,
                "wakeword_loaded": self.wakeword_loaded,
                "wakeword_active": self.wakeword_active,
                "wakeword_score": round(self.wakeword_score, 3),
                "wakeword_max_score": round(self.wakeword_max_score, 3),
                "wakeword_threshold": self.wakeword_threshold,
                "whisper_loaded": self.whisper_loaded,
                "recording": self.recording,
                "processing": self.processing,
                "conversation_active": self.conversation_active,
                "conversation_state": self.conversation_state,
                "conversation_session_id": self.conversation_session_id,
                "conversation_started_at": self.conversation_started_at,
                "conversation_last_activity": self.conversation_last_activity,
                "conversation_turns": self.conversation_turns,
                "conversation_topic": self.conversation_topic,
                "conversation_task": self.conversation_task,
                "conversation_pending_question": self.conversation_pending_question,
                "conversation_pending_confirmation": self.conversation_pending_confirmation,
                "conversation_interrupted": self.conversation_interrupted,
                "conversation_summary": self.conversation_summary,
                "waiting_for_reply": self.waiting_for_reply,
                "input_level": round(self.input_level, 3),
                "frames_per_second": round(self.frames_per_second, 1),
                "last_audio_error": self.last_audio_error,
            }

    def update(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)
