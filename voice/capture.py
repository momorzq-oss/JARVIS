"""
Shared audio capture service.

Opens ONE microphone stream (sounddevice / PortAudio) and fans each int16
16 kHz frame out to registered subscribers:
  - the OpenWakeWord detector
  - the command recorder (Whisper input)
  - the GUI input-level meter

This replaces the old design where the wake-word engine and the Whisper
recorder each opened their own competing streams. Sample format matches what
OpenWakeWord expects (16 kHz, mono, int16).
"""
import threading
import time

import numpy as np

from voice import audio_log

SAMPLE_RATE = 16000
CHUNK = 1280          # 80 ms @ 16 kHz - exactly what OpenWakeWord wants


class AudioCaptureService:
    def __init__(self, device_index=None):
        self.device_index = device_index
        self.device_name = ""
        self._stream = None
        self._subscribers = []
        self._lock = threading.RLock()
        self._running = False
        self._level = 0.0
        self._frames = 0
        self._fps = 0.0
        self._fps_window_start = time.time()
        self._fps_window_frames = 0
        self._stream_status = ""
        self._stream_status_count = 0
        self._stream_status_reported = 0
        self._last_status_report_at = 0.0
        self.last_error = ""

    # ------------------------------------------------------------ subscribe
    def subscribe(self, callback):
        """callback(np.int16 mono frame of CHUNK samples)."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback):
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    # ------------------------------------------------------------ properties
    @property
    def running(self):
        return self._running

    @property
    def level(self):
        return self._level

    @property
    def fps(self):
        return self._fps

    # ------------------------------------------------------------ lifecycle
    def start(self):
        """Open the mic stream and start receiving frames. Returns True."""
        with self._lock:
            if self._running:
                audio_log.log("Microphone stream already running")
                return True
            try:
                import sounddevice as sd
                audio_log.log(f"Requesting microphone stream (device={self.device_index})")
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="int16",
                    blocksize=CHUNK,
                    # Wake inference is intentionally off the callback thread,
                    # but Windows MME still needs enough host buffering while
                    # ONNX/Whisper workers briefly compete for CPU time.
                    latency="high",
                    device=self.device_index,
                    callback=self._callback,
                )
                stream.start()
                self._stream = stream
                self._running = True
                try:
                    self.device_name = sd.query_devices(self.device_index)["name"] \
                        if self.device_index is not None else \
                        sd.query_devices(sd.default.device[0])["name"]
                except Exception:
                    self.device_name = "microphone"
                audio_log.log(f"Microphone stream opened on '{self.device_name}'")
                return True
            except Exception as exc:
                self.last_error = str(exc)
                self._running = False
                self._stream = None
                audio_log.log_error(f"Failed to open microphone stream: {exc}", exc)
                return False

    def _callback(self, indata, frames, time_info, status):
        if status:
            # Never perform file I/O from PortAudio's real-time callback. A
            # synchronous overflow log made the callback even later and could
            # sustain an overflow/logging feedback loop. The voice worker
            # consumes this compact diagnostic outside the audio thread.
            self._stream_status = str(status)
            self._stream_status_count += 1
        try:
            audio = np.frombuffer(indata, dtype=np.int16).copy()
        except Exception:
            return
        # input level (0..1) for the GUI meter
        try:
            peak = float(np.max(np.abs(audio))) / 32768.0
            self._level = 0.7 * self._level + 0.3 * peak
        except Exception:
            pass
        self._frames += 1
        self._fps_window_frames += 1
        now = time.time()
        elapsed = now - self._fps_window_start
        if elapsed >= 1.0:
            self._fps = self._fps_window_frames / elapsed
            self._fps_window_frames = 0
            self._fps_window_start = now
        with self._lock:
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(audio)
            except Exception as exc:
                audio_log.log_error(f"Subscriber error: {exc}", exc)

    def consume_stream_status(self, interval_seconds=5.0):
        """Return a throttled callback diagnostic for a non-realtime worker."""
        count = self._stream_status_count
        now = time.monotonic()
        if (count <= self._stream_status_reported
                or now - self._last_status_report_at < interval_seconds):
            return ""
        delta = count - self._stream_status_reported
        self._stream_status_reported = count
        self._last_status_report_at = now
        return f"{self._stream_status} ({delta} occurrence{'s' if delta != 1 else ''})"

    def stop(self):
        """Close the mic stream."""
        with self._lock:
            self._running = False
            stream = self._stream
            self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
                audio_log.log("Microphone stream closed")
            except Exception as exc:
                audio_log.log_error(f"Error closing stream: {exc}", exc)
        audio_log.log("Voice worker stopped")
