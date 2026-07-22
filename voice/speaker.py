"""Offline Piper text-to-speech and local ``sounddevice`` playback.

Piper is the sole production speech engine. Playback uses the already required
sounddevice/PortAudio stack instead of pygame, which has no compatible wheel
for the Python 3.14 runtime used by the live JARVIS launcher.
"""
from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

from config import Config
from voice import audio_log


def _clean_for_speech(text):
    """Strip markdown-style artifacts before sending text to Piper."""
    cleaned = str(text)
    cleaned = re.sub(r"[*_`#>]", "", cleaned)
    cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


class Speaker:
    """Non-blocking Piper synthesis with cancellable local audio playback."""

    def __init__(self, voice=None, rate=None, pitch=None, output_device=None):
        # Retain these arguments for compatibility with older callers. Piper's
        # voice and prosody come from its selected local ONNX model.
        self.voice = voice or str(Config.PIPER_MODEL)
        self.rate = rate
        self.pitch = pitch
        self._stop = threading.Event()
        self._speaking = threading.Event()
        self._lock = threading.RLock()
        self._piper_lock = threading.Lock()
        self._playback_lock = threading.RLock()
        self._thread_local = threading.local()
        self._thread = None
        self._piper_voice = None
        self._output_stream = None
        self._output_device = self._normalise_device(output_device)
        self._output_device_name = ""
        self._ready = False
        self.last_engine = "piper"
        self.last_error = ""
        self._init_playback()

    @staticmethod
    def _normalise_device(device):
        if isinstance(device, dict):
            device = device.get("index")
        if device in (None, "", "default"):
            return None
        try:
            return int(device)
        except (TypeError, ValueError):
            return None

    def _init_playback(self):
        """Validate a real output device without opening a persistent stream."""
        with self._playback_lock:
            try:
                import sounddevice as sd

                info = sd.query_devices(self._output_device, kind="output")
                self._output_device_name = str(info.get("name", "output device"))
                self._ready = True
                self.last_error = ""
            except Exception as exc:
                self._ready = False
                self._output_device_name = ""
                self.last_error = f"Piper playback output unavailable: {exc}"
                audio_log.log_error(self.last_error, exc)
        return self._ready

    def set_output_device(self, device):
        """Select a PortAudio output index, or ``default`` for Windows default."""
        self.stop()
        with self._playback_lock:
            self._output_device = self._normalise_device(device)
        return self._init_playback()

    @property
    def output_device_name(self):
        return self._output_device_name or "Unavailable"

    @property
    def speaking(self):
        return self._speaking.is_set()

    def speak(self, text, block=False):
        """Speak text through Piper, or report the specific output failure."""
        text = _clean_for_speech(text)
        if not text:
            return False
        if not self._ready and not self._init_playback():
            raise RuntimeError(self.last_error or "Piper playback is unavailable")

        self.stop()
        self.last_error = ""
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run, args=(text, stop_event), daemon=True, name="jarvis-piper"
        )
        with self._lock:
            self._stop = stop_event
            self._thread = thread
        thread.start()
        if block:
            thread.join()
        return True

    def stop(self):
        """Cancel Piper playback without touching the active microphone stream."""
        self._stop.set()
        with self._playback_lock:
            stream = self._output_stream
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
        if os.name == "nt" and self._output_device is None:
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

    def wait(self, timeout=None):
        """Wait for the current speech request to finish."""
        start = time.monotonic()
        while self._speaking.is_set():
            if timeout is not None and time.monotonic() - start >= timeout:
                return False
            time.sleep(0.05)
        return True

    def _should_stop(self):
        event = getattr(self._thread_local, "stop_event", None)
        return (event or self._stop).is_set()

    def _run(self, text, stop_event):
        self._thread_local.stop_event = stop_event
        self._speaking.set()
        tmp_path = None
        try:
            tmp_path = self._synthesize(text)
            if self._should_stop():
                return
            self._play_wav(tmp_path)
            if not self._should_stop():
                audio_log.log("Piper playback completed")
        except Exception as exc:
            self.last_error = f"Piper speech failed: {exc}"
            audio_log.log_error(self.last_error, exc)
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
            with self._lock:
                if self._thread is threading.current_thread():
                    self._speaking.clear()

    @staticmethod
    def _temp_path(suffix):
        fd, raw_path = tempfile.mkstemp(suffix=suffix, prefix="jarvis_piper_")
        os.close(fd)
        return Path(raw_path)

    def _synthesize(self, text):
        path = self._temp_path(".wav")
        try:
            self._synth_piper(text, path)
            if path.stat().st_size <= 44:
                raise RuntimeError("Piper returned no audio")
            self.last_engine = "piper"
            return path
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def _synth_piper(self, text, path: Path):
        model_path = Path(Config.PIPER_MODEL)
        if not model_path.is_file():
            raise FileNotFoundError(f"Piper model not found: {model_path}")
        with self._piper_lock:
            if self._piper_voice is None:
                from piper import PiperVoice
                self._piper_voice = PiperVoice.load(model_path)
            with wave.open(str(path), "wb") as wav_file:
                self._piper_voice.synthesize_wav(text, wav_file)

    def _play_wav(self, path: Path):
        """Play a Piper WAV with a stream that ``stop`` can abort safely."""
        with wave.open(str(path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            frames = wav_file.readframes(frame_count)

        # Windows' native WAV player is the most reliable route for the
        # configured default output. It keeps playback out of Python callback
        # scheduling while the microphone/wake-word workers are active.
        if os.name == "nt" and self._output_device is None:
            self._play_default_windows_wav(path, frame_count, sample_rate)
            return

        if sample_width == 2:
            audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        elif sample_width == 4:
            audio = np.frombuffer(frames, dtype="<f4").astype(np.float32)
        else:
            raise RuntimeError(f"Unsupported Piper WAV sample width: {sample_width}")
        # sounddevice callbacks always receive ``(frames, channels)`` output.
        # Keep Piper's mono audio explicitly two-dimensional so it cannot be
        # mistaken for a broadcastable row vector by NumPy.
        audio = audio.reshape(-1, channels)
        if not len(audio):
            raise RuntimeError("Piper generated an empty WAV")

        import sounddevice as sd

        cursor = [0]
        finished = threading.Event()

        def callback(outdata, frame_count, time_info, status):
            if status:
                audio_log.log(f"Piper output status: {status}")
            if self._should_stop():
                raise sd.CallbackAbort
            available = len(audio) - cursor[0]
            take = min(frame_count, max(0, available))
            outdata.fill(0)
            if take:
                outdata[:take] = audio[cursor[0]:cursor[0] + take]
                cursor[0] += take
            if take < frame_count:
                raise sd.CallbackStop

        with self._playback_lock:
            if not self._ready and not self._init_playback():
                raise RuntimeError(self.last_error or "No output device")
            stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                device=self._output_device,
                latency="high",
                blocksize=2048,
                callback=callback,
                finished_callback=finished.set,
            )
            self._output_stream = stream

        try:
            with stream:
                while not finished.wait(0.05):
                    if self._should_stop():
                        stream.abort()
                        return
        finally:
            with self._playback_lock:
                if self._output_stream is stream:
                    self._output_stream = None

    def _play_default_windows_wav(self, path: Path, frame_count: int, sample_rate: int):
        import winsound

        duration = max(0.05, float(frame_count) / max(1, sample_rate))
        winsound.PlaySound(
            str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        )
        deadline = time.monotonic() + duration + 0.2
        while time.monotonic() < deadline:
            if self._should_stop():
                try:
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception:
                    pass
                return
            time.sleep(0.03)
