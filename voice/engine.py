"""
Voice engine - orchestrates the live voice session on ONE background thread
fed by the shared AudioCaptureService.

Pipeline:
  wake-word frames -> OpenWakeWord -> on detection, record command via VAD ->
  Faster Whisper transcription -> AssistantController.handle_text -> speak.

The engine thread is stored as an instance attribute and signals connect
before start, so nothing is garbage-collected mid-session. start() marks the
microphone ON only after the stream actually opens; failures surface the
exact error and leave typed mode working.
"""
import queue
import threading
import time

import numpy as np

from config import Config
from voice import audio_log
from voice.capture import AudioCaptureService, SAMPLE_RATE, CHUNK

# Original imports from main.py, uncommented.
from main import YES_WORDS, NO_WORDS, CANCEL_WORDS

VAD_FRAME = 480        # 30 ms @ 16 kHz for webrtcvad
WAKE_POLL_SECONDS = 0.5
SPEECH_COOLDOWN_SECONDS = 0.9


class VoiceEngine:
    def __init__(self, controller, state, speech, wakeword_model=None,
                 threshold=None, device_index=None, wake_engine=None):
        self.controller = controller
        self.state = state
        self.speech = speech
        self.wakeword_model = wakeword_model or Config.WAKE_WORD
        self.threshold = threshold if threshold is not None else Config.WAKE_THRESHOLD
        self.capture = AudioCaptureService(device_index=device_index)
        self._thread = None
        self._wake_thread = None
        self._wake_frames = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._lifecycle_generation = 0
        self._running = False
        self._wake = wake_engine
        self._listener = None
        self._frame_queue = []
        self._queue_lock = threading.Lock()
        self._wake_event = threading.Event()
        self._wake_session_active = threading.Event()
        self._wake_suppressed_until = 0.0
        self._diag = False
        self._last_score = 0.0
        self._wake_voice_hangover = 0

    # ------------------------------------------------------------ properties
    @property
    def running(self):
        return self._running

    def set_diagnostic(self, on):
        self._diag = bool(on)

    # ------------------------------------------------------------ lifecycle
    def start(self):
        """Open mic, load wake word + whisper, start the engine thread."""
        audio_log.log("Start Voice requested")
        if self._running:
            audio_log.log("Voice engine already running")
            return True
        with self._lifecycle_lock:
            self._lifecycle_generation += 1
            generation = self._lifecycle_generation
            self._stop.clear()

        def cancelled():
            with self._lifecycle_lock:
                return (
                    self._stop.is_set()
                    or generation != self._lifecycle_generation
                )

        # 1) load the wake model before opening the real-time stream.  ONNX
        # initialization can hold the GIL for several seconds; opening the
        # microphone first made PortAudio callbacks overflow while no audio
        # could be processed yet.
        self.state.update(microphone_active=False)
        try:
            if self._wake is None:
                from voice.wakeword import WakeWordEngine
                self._wake = WakeWordEngine(model_name=self.wakeword_model,
                                            threshold=self.threshold)
            audio_log.log("Wake-word worker started")
            if not self._wake._ensure_loaded():
                raise RuntimeError(self._wake.load_error or "wake model load failed")
            if cancelled():
                audio_log.log("Voice startup cancelled during wake-word load")
                return False
            self.state.update(wakeword_loaded=True, wakeword_active=True,
                              wakeword_threshold=self.threshold)
            audio_log.log(f"Wake-word model loaded: {self.wakeword_model} "
                          f"(threshold {self.threshold})")
        except Exception as exc:
            self.state.update(wakeword_loaded=False, wakeword_active=False,
                              last_audio_error=str(exc))
            audio_log.log_error(f"Wake-word load failed: {exc}", exc)
            return False

        # 2) listener (whisper) - reuse the controller's listener
        self._listener = self.controller.ctx.listener
        try:
            self.state.update(whisper_loaded=getattr(self._listener, "_model", None) is not None)
        except Exception:
            pass

        if cancelled():
            audio_log.log("Voice startup cancelled before microphone open")
            return False

        # 3) open microphone only when the consumer is ready.  The UI marks
        # the microphone ON only after the stream has actually opened.
        if not self.capture.start():
            err = self.capture.last_error or "unknown microphone error"
            self.state.update(microphone_active=False, microphone_available=False,
                              last_audio_error=err)
            audio_log.log_error(f"Voice startup failed (microphone): {err}")
            return False
        if cancelled():
            self.capture.stop()
            self.state.update(microphone_active=False, wakeword_active=False)
            audio_log.log("Voice startup cancelled after microphone open")
            return False
        self.state.update(microphone_active=True, microphone_available=True,
                          selected_microphone=self.capture.device_name)
        audio_log.log(f"Microphone ON: {self.capture.device_name}")

        # 4) subscribe wake-word frames + start engine thread
        self._wake_event.clear()
        self._wake_session_active.clear()
        self._wake_suppressed_until = 0.0
        # The PortAudio callback must only copy/queue audio.  OpenWakeWord
        # inference is real work and can otherwise overflow the device callback
        # or starve Qt's presentation thread while the microphone is active.
        self.capture.subscribe(self._enqueue_wake_frame)
        self._wake_thread = threading.Thread(
            target=self._wake_frame_loop,
            daemon=True,
            name="JarvisWakeInference",
        )
        self._wake_thread.start()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="JarvisVoiceEngine")
        self._thread.start()          # called exactly once
        if cancelled():
            self.stop()
            return False
        self._running = True
        audio_log.log("Voice engine thread started")
        return True

    # ------------------------------------------------------------ frame feed
    def _enqueue_wake_frame(self, audio):
        """Keep the newest audio without blocking PortAudio's callback."""
        try:
            # AudioCaptureService already owns a copied int16 frame.  Copying
            # it again in PortAudio's callback needlessly lengthened the
            # real-time callback and increased Windows input overflows.
            self._wake_frames.put_nowait(audio)
            return
        except queue.Full:
            pass
        try:
            self._wake_frames.get_nowait()
        except queue.Empty:
            pass
        try:
            self._wake_frames.put_nowait(audio)
        except queue.Full:
            pass

    def _wake_frame_loop(self):
        while not self._stop.is_set():
            try:
                frame = self._wake_frames.get(timeout=0.2)
            except queue.Empty:
                continue
            if frame is None:
                return
            stream_status = self.capture.consume_stream_status()
            if stream_status:
                audio_log.log(f"Stream status: {stream_status}")
            self._on_wake_frame(frame)

    def _speech_active(self):
        return bool(getattr(self.speech, "speaking", False))

    def _wake_audio_active(self, audio):
        """Use the existing local VAD to avoid inference on room silence.

        Eight 80 ms hangover frames preserve the end of "Hey Jarvis" and its
        immediate acoustic context. If VAD is unavailable, wake processing
        remains enabled so this optimization can never disable the feature.
        """
        vad = getattr(self._listener, "_vad", None)
        if vad is None:
            return True
        frame = np.asarray(audio, dtype=np.int16).reshape(-1)
        try:
            voiced = any(
                vad.is_speech(frame[start:start + 320].tobytes(), SAMPLE_RATE)
                for start in range(0, len(frame) - 319, 320)
            )
        except Exception:
            return True
        if voiced:
            self._wake_voice_hangover = 8
            return True
        if self._wake_voice_hangover > 0:
            self._wake_voice_hangover -= 1
            return True
        return False

    def _reset_wake_model(self):
        model = getattr(self._wake, "_model", None)
        reset = getattr(model, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                pass

    def _on_wake_frame(self, audio):
        """Called from the capture callback for every CHUNK frame."""
        if self._wake is None or self._stop.is_set():
            return
        self.state.update(
            input_level=self.capture.level,
            frames_per_second=self.capture.fps,
        )
        if self._wake_session_active.is_set():
            return
        now = time.monotonic()
        if self._speech_active():
            self._wake_suppressed_until = now + SPEECH_COOLDOWN_SECONDS
            return
        if now < self._wake_suppressed_until:
            return
        if not self._wake_audio_active(audio):
            self.state.update(wakeword_score=0.0)
            return
        try:
            prediction = self._wake.process(audio)
            self.state.update(
                wakeword_score=prediction,
                wakeword_max_score=max(
                    getattr(self.state, "wakeword_max_score", 0.0), prediction
                ),
            )
            if prediction > self.threshold:
                if self._wake_session_active.is_set():
                    return
                self._wake_session_active.set()
                self._reset_wake_model()
                audio_log.log(f"Wake-word detected ({prediction:.2f})")
                self._wake_event.set()
                self.controller._emit("wakeword", "detected")
            if self._diag:
                if prediction > 0.05: # log anything above noise
                    audio_log.log(f"[diag] wake score: {prediction:.2f}")
                else:
                    audio_log.log("[diag] wake score: <0.05")
            self._last_score = prediction
        except Exception as exc:
            audio_log.log_error(f"Wake-word processing failed: {exc}", exc)

    def _finish_voice_cycle(self):
        self.state.update(recording=False, processing=False)
        while self._speech_active() and not self._stop.is_set():
            self._wake_suppressed_until = (
                time.monotonic() + SPEECH_COOLDOWN_SECONDS
            )
            time.sleep(0.05)
        if not self._stop.is_set():
            self._wake_suppressed_until = (
                time.monotonic() + SPEECH_COOLDOWN_SECONDS
            )
            while (time.monotonic() < self._wake_suppressed_until
                   and not self._stop.is_set()):
                time.sleep(0.05)
        self._reset_wake_model()
        self._wake_event.clear()
        self._wake_session_active.clear()
        if not self._stop.is_set():
            self.controller._set_state(
                "listening_wake", "Listening for Hey Jarvis"
            )
            self.state.update(wakeword_active=True)

    def _run(self):
        """Main voice engine thread loop."""
        while not self._stop.is_set():
            triggered = self._wake_event.wait(WAKE_POLL_SECONDS)
            if self._stop.is_set():
                break
            if not triggered:
                continue
            self._wake_event.clear()
            if not self._wake_session_active.is_set():
                continue
            try:
                self.controller._set_state("wake_detected", "Wake word detected")
                self.speech.stop()
                self.controller._emit("wakeword", "command")
                self.state.update(wakeword_active=False, recording=True)

                self.controller._set_state("recording", "Recording command")
                audio_log.log("Command recording started")
                audio = self._record_command()
                if self._stop.is_set():
                    continue
                if audio.size == 0:
                    audio_log.log("Command recording timed out without speech")
                    self.speech.speak("I didn't hear anything, sir.")
                    continue

                self.state.update(recording=False)
                self.controller._set_state("processing", "Processing command")
                self._do_transcription_and_route(audio)
            finally:
                self._finish_voice_cycle()

    def _do_transcription_and_route(self, audio):
        if self._stop.is_set():
            return
        self.state.update(processing=True)
        try:
            # ensure whisper model is loaded (it's preloaded, but just in case)
            self.controller.ctx.listener.preload()
            self.state.update(whisper_loaded=True)
            text = self._listener.transcribe(audio)
        except Exception as exc:
            text = ""
            self.state.update(last_audio_error=str(exc))
            audio_log.log_error(f"Whisper transcription failed: {exc}", exc)
        self.state.update(processing=False)
        audio_log.log(f"Transcription completed: {len(text)} characters")
        if not text:
            self.speech.speak("I didn't catch that, sir.")
            self.controller._set_state("listening_wake", "Listening for Hey Jarvis")
            return
        
        # Re-enabled voice confirmation logic.
        gui_controller_instance = self.controller.ctx.gui_controller if hasattr(self.controller.ctx, 'gui_controller') else None
        if (gui_controller_instance
                and hasattr(gui_controller_instance, 'confirmation_pending')
                and gui_controller_instance.confirmation_pending()):
            audio_log.log("[VoiceEngine] Confirmation pending, checking voice command.")
            cleaned_text = text.lower().strip()
            if cleaned_text in YES_WORDS:
                gui_controller_instance.resolve_confirmation("approve_once")
                self.speech.speak("Confirmed, sir.")
                return # Handled by voice confirmation
            elif cleaned_text in CANCEL_WORDS:
                gui_controller_instance.resolve_confirmation("cancel_task")
                self.speech.speak("Task cancelled, sir.")
                return
            elif cleaned_text in NO_WORDS:
                gui_controller_instance.resolve_confirmation("deny")
                self.speech.speak("Action cancelled, sir.")
                return # Handled by voice confirmation
            else:
                self.speech.speak("Please say yes or no to confirm the action, or cancel to abort.")
                return # Still waiting for confirmation

        # route command to controller (original logic)
        self.controller._emit("transcription", text)
        audio_log.log(f"Command sent to router: {len(text)} characters")
        spoken = self.controller.handle_text(text, from_voice=True)
        audio_log.log(
            f"Response returned: {len(spoken) if isinstance(spoken, str) else 0} characters"
        )
        # ``AssistantController.handle_text`` delegates normal commands to
        # ``main.handle_utterance``, which owns normal response playback.
        # Speaking ``spoken`` here as well played every voice-command response
        # twice, with the two Piper jobs overlapping.
        if not self._stop.is_set():
            self.controller._set_state("listening_wake", "Listening for Hey Jarvis")

    # ------------------------------------------------------------ recording
    def _record_command(self, max_seconds=None):
        """Record a command from the shared stream using VAD on queue frames."""
        max_seconds = max_seconds or Config.LISTEN_MAX_SECONDS
        # clear stale frames and subscribe
        with self._queue_lock:
            self._frame_queue = []
        self.capture.subscribe(self._on_record_frame)
        try:
            frames = []
            voiced_run = 0
            started = False
            silent_run = 0
            waited = 0
            start_timeout_frames = int(5.0 * 1000 / 30)
            silence_frames = 26
            max_frames = int(max_seconds * 1000 / 30)
            count = 0
            while count < max_frames and not self._stop.is_set():
                frame = self._next_frame(timeout=0.5)
                if frame is None:
                    if not started:
                        waited += 16
                        if waited > start_timeout_frames:
                            return np.array([], dtype=np.int16)
                    continue
                count += 1
                # split CHUNK (1280) into 30ms VAD frames (480) - process subframes
                for sub in self._subframes(frame):
                    pcm = sub.tobytes()
                    try:
                        voiced = self._listener._vad.is_speech(pcm, SAMPLE_RATE)
                    except Exception:
                        voiced = False
                    if not started:
                        waited += 1
                        if voiced:
                            voiced_run += 1
                        else:
                            voiced_run = max(0, voiced_run - 1)
                        if voiced_run >= 3:
                            started = True
                            frames.append(pcm)
                        elif waited > start_timeout_frames:
                            return np.array([], dtype=np.int16)
                    else:
                        frames.append(pcm)
                        if voiced:
                            silent_run = 0
                        else:
                            silent_run += 1
                            if silent_run >= silence_frames:
                                return np.frombuffer(b"".join(frames), dtype=np.int16)
            return np.frombuffer(b"".join(frames), dtype=np.int16) if frames \
                else np.array([], dtype=np.int16)
        finally:
            self.capture.unsubscribe(self._on_record_frame)

    def _on_record_frame(self, audio):
        with self._queue_lock:
            self._frame_queue.append(audio)

    def _next_frame(self, timeout=0.5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._queue_lock:
                if self._frame_queue:
                    return self._frame_queue.pop(0)
            time.sleep(0.01)
        return None

    def _subframes(self, frame):
        # yield 480-sample VAD subframes from a CHUNK frame
        for start in range(0, len(frame) - VAD_FRAME + 1, VAD_FRAME):
            yield frame[start:start + VAD_FRAME]

    # ------------------------------------------------------------ stop
    def stop(self):
        audio_log.log("Stop Voice requested")
        with self._lifecycle_lock:
            self._lifecycle_generation += 1
        self._stop.set()
        self._wake_event.set()        # unblock waiters
        try:
            self.capture.unsubscribe(self._enqueue_wake_frame)
        except Exception:
            pass
        try:
            self._wake_frames.put_nowait(None)
        except queue.Full:
            try:
                self._wake_frames.get_nowait()
                self._wake_frames.put_nowait(None)
            except (queue.Empty, queue.Full):
                pass
        self.capture.stop()
        if self._wake_thread is not None and self._wake_thread.is_alive():
            self._wake_thread.join(timeout=3)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._running = False
        self._wake_session_active.clear()
        self._wake_suppressed_until = 0.0
        self.state.update(microphone_active=False, wakeword_active=False,
                          recording=False, processing=False)
        audio_log.log("Voice engine stopped; microphone OFF")
