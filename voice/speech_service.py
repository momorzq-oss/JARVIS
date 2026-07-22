"""Shared Piper-only speech service with truthful GUI status reporting."""
from __future__ import annotations

import threading

from voice import audio_log


class SpeechOutputService:
    def __init__(self, speaker=None, state=None):
        self.speaker = speaker
        self.state = state
        self._muted = False
        self._lock = threading.RLock()
        self._speaker_state = "ready"
        self._engine = "Piper"
        self._available = True

    def attach(self, speaker, state):
        self.speaker = speaker
        self.state = state

    def _set(self, **kwargs):
        if self.state is not None:
            self.state.update(**kwargs)

    @property
    def muted(self):
        return self._muted

    @property
    def speaking(self):
        return bool(self.speaker is not None and self.speaker.speaking)

    def available(self):
        return self._available

    def speak(self, text, block=False):
        if self._muted:
            audio_log.log("Piper speech suppressed (muted)")
            self._set(speaker_state="muted")
            return False
        if self.speaker is None:
            self._available = False
            self._set(speaker_state="unavailable", speaker_available=False)
            return False
        self._set(speaker_state="speaking", speaker_available=True,
                  speaker_engine="Piper")
        try:
            self.speaker.speak(text, block=block)
        except Exception as exc:
            audio_log.log_error(f"Speech error: {exc}", exc)
            self._available = False
            self._set(speaker_state="error", speaker_available=False,
                      speaker_engine="Piper")
            return False
        self._available = True
        audio_log.log("Piper playback queued")
        self._set(speaker_engine="Piper")
        self._set(speaker_state="speaking" if self.speaker.speaking else "ready")
        return True

    def note_engine(self):
        if self.speaker is None:
            return
        self._set(speaker_engine="Piper", speaker_available=True,
                  speaker_state="ready" if not self._muted else "muted")

    def sync_state(self):
        if self.speaker is None:
            self._available = False
            self._set(speaker_available=False, speaker_state="unavailable")
        elif self._muted:
            self._set(speaker_state="muted", speaker_available=True)
        elif getattr(self.speaker, "last_error", ""):
            self._available = False
            self._set(speaker_state="error", speaker_available=False,
                      speaker_engine="Piper")
        elif self.speaker.speaking:
            self._available = True
            self._set(speaker_state="speaking", speaker_available=True,
                      speaker_engine="Piper")
        else:
            self._available = True
            self._set(speaker_state="ready", speaker_available=True,
                      speaker_engine="Piper")

    def mute(self):
        with self._lock:
            self._muted = True
        try:
            if self.speaker is not None:
                self.speaker.stop()
        except Exception:
            pass
        self._set(speaker_state="muted")
        audio_log.log("Speaker muted")

    def unmute(self):
        with self._lock:
            self._muted = False
        self._set(speaker_state="ready")
        audio_log.log("Speaker unmuted")

    def stop(self):
        try:
            if self.speaker is not None:
                self.speaker.stop()
        except Exception:
            pass

    def wait(self, timeout=None):
        if self.speaker is not None:
            return self.speaker.wait(timeout=timeout)
        return True

    def set_output_device(self, device):
        if self.speaker is None or not hasattr(self.speaker, "set_output_device"):
            self._available = False
            self._set(speaker_state="unavailable", speaker_available=False)
            return False
        try:
            ok = bool(self.speaker.set_output_device(device))
        except Exception as exc:
            audio_log.log_error(f"Speaker device update failed: {exc}", exc)
            ok = False
        self._available = ok
        self._set(speaker_state="ready" if ok else "error", speaker_available=ok,
                  speaker_engine="Piper")
        return ok
