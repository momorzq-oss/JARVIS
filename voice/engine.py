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
from core.conversation import (
    CONVERSATION_LISTENING,
    ENDING_CONVERSATION,
    ERROR_RECOVERY,
    EXECUTING_TOOL,
    INTENT_CONVERSATION,
    INTENT_CORRECTION,
    INTENT_EXIT,
    INTENT_FOLLOW_UP,
    INTENT_QUESTION,
    INTERRUPTED,
    SLEEPING,
    SPEAKING,
    THINKING,
    TRANSCRIBING,
)

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
        self._conversation_empty_transcriptions = 0

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
        manager = self._conversation_manager()
        if manager is not None and not manager.active:
            manager.set_state(SLEEPING)
            self.state.update(**manager.snapshot(), waiting_for_reply=False)
        if not self._stop.is_set():
            self.controller._set_state(
                "listening_wake", "Listening for Hey Jarvis"
            )
            self.state.update(wakeword_active=True)

    def _conversation_manager(self):
        return getattr(self.controller, "conversation", None)

    def _conversation_settings(self):
        manager = self._conversation_manager()
        return getattr(manager, "settings", None)

    def _conversation_enabled(self):
        settings = self._conversation_settings()
        return bool(
            settings is not None
            and settings.enabled
            and settings.follow_up_listening
        )

    def _update_conversation_state(self, state, detail="", **extra):
        manager = self._conversation_manager()
        if manager is not None:
            try:
                manager.set_state(state)
                self.state.update(**manager.snapshot())
            except Exception:
                pass
        self.state.update(**extra)
        if detail:
            self.controller._set_state(str(state).lower(), detail)
        self.controller._emit("voicestate", self.state.snapshot())
        audio_log.log(f"Conversation state: {state} {detail}".strip())

    def _wait_for_speech_idle(self, settings, allow_barge=False):
        """Wait for TTS to finish; optionally stop playback when human speech starts."""
        if not self._speech_active():
            self._post_speech_delay(settings)
            return False
        self._update_conversation_state(SPEAKING, "Speaking")
        if not allow_barge:
            while self._speech_active() and not self._stop.is_set():
                time.sleep(0.05)
            self._post_speech_delay(settings)
            return False

        with self._queue_lock:
            self._frame_queue = []
        self.capture.subscribe(self._on_record_frame)
        voiced_run = 0
        try:
            while self._speech_active() and not self._stop.is_set():
                frame = self._next_frame(timeout=0.08)
                if frame is None:
                    continue
                if self._frame_has_voice(frame, settings):
                    voiced_run += 1
                else:
                    voiced_run = max(0, voiced_run - 1)
                if voiced_run >= max(1, int(settings.speech_start_threshold)):
                    self.speech.stop()
                    manager = self._conversation_manager()
                    if manager is not None:
                        manager.mark_interrupted()
                        self.state.update(**manager.snapshot())
                    self._update_conversation_state(INTERRUPTED, "Interrupted")
                    return True
        finally:
            self.capture.unsubscribe(self._on_record_frame)
        self._post_speech_delay(settings)
        return False

    def _post_speech_delay(self, settings):
        delay = getattr(settings, "post_speech_delay_seconds", 0.35) if settings else 0.35
        deadline = time.monotonic() + max(0.0, float(delay))
        while time.monotonic() < deadline and not self._stop.is_set():
            time.sleep(0.03)

    def _activate_conversation_after_turn(self, turn):
        if not self._conversation_enabled() or self._stop.is_set():
            return False
        text = str((turn or {}).get("text") or "").strip()
        spoken = str((turn or {}).get("spoken") or "").strip()
        if not text:
            return False
        manager = self._conversation_manager()
        if manager is None:
            return False
        manager.begin(user_text=text, current_task=text)
        if spoken:
            manager.record_assistant(spoken)
        self._conversation_empty_transcriptions = 0
        self.state.update(**manager.snapshot())
        self.controller._emit("voicestate", self.state.snapshot())
        audio_log.log("Conversation mode entered")
        return True

    def _record_wake_only_followup(self):
        if not self._conversation_enabled() or self._stop.is_set():
            return np.array([], dtype=np.int16)
        settings = self._conversation_settings()
        self.speech.speak("Yes?")
        self._wait_for_speech_idle(settings, allow_barge=False)
        if self._stop.is_set():
            return np.array([], dtype=np.int16)
        self._update_conversation_state(
            CONVERSATION_LISTENING,
            "Waiting for your first message",
            wakeword_active=False,
            waiting_for_reply=True,
            recording=True,
        )
        audio = self._record_command(
            max_seconds=settings.maximum_recording_seconds,
            start_timeout=settings.first_silence_reminder_seconds,
            silence_timeout=settings.silence_detection_seconds,
            min_speech_seconds=settings.minimum_speech_seconds,
            speech_start_threshold=settings.speech_start_threshold,
            background_noise_threshold=settings.background_noise_threshold,
            background_noise_filtering=settings.background_noise_filtering,
        )
        self.state.update(recording=False, waiting_for_reply=False)
        return audio

    def _run_conversation_loop(self):
        manager = self._conversation_manager()
        settings = self._conversation_settings()
        if manager is None or settings is None or not manager.active:
            return
        reminders = 0
        while manager.active and not self._stop.is_set():
            allow_barge = bool(
                settings.barge_in and not settings.echo_suppression
            )
            self._wait_for_speech_idle(settings, allow_barge=allow_barge)
            if not manager.active or self._stop.is_set():
                break
            self._update_conversation_state(
                CONVERSATION_LISTENING,
                "Waiting for your reply",
                wakeword_active=False,
                waiting_for_reply=True,
                recording=True,
            )
            wait_seconds = self._next_conversation_wait(settings, reminders)
            audio = self._record_command(
                max_seconds=settings.maximum_recording_seconds,
                start_timeout=wait_seconds,
                silence_timeout=settings.silence_detection_seconds,
                min_speech_seconds=settings.minimum_speech_seconds,
                speech_start_threshold=settings.speech_start_threshold,
                background_noise_threshold=settings.background_noise_threshold,
                background_noise_filtering=settings.background_noise_filtering,
            )
            self.state.update(recording=False, waiting_for_reply=False)
            if self._stop.is_set() or not manager.active:
                break
            if audio.size == 0:
                reminders = self._handle_conversation_silence(settings, reminders)
                continue
            reminders = 0
            turn = self._do_transcription_and_route(audio, conversation_turn=True)
            if not turn.get("text"):
                if self._handle_empty_conversation_transcription():
                    break
                continue
            if turn.get("exit"):
                break
            self._conversation_empty_transcriptions = 0

    def _next_conversation_wait(self, settings, reminders):
        now = time.time()
        manager = self._conversation_manager()
        last = manager.session.last_activity_time if manager is not None else now
        elapsed = max(0.0, now - last)
        timeout = max(1.0, settings.inactivity_timeout_seconds - elapsed)
        if reminders <= 0:
            target = max(1.0, settings.first_silence_reminder_seconds - elapsed)
        elif reminders == 1:
            target = max(1.0, settings.second_silence_reminder_seconds - elapsed)
        else:
            target = timeout
        return min(timeout, target)

    def _handle_conversation_silence(self, settings, reminders):
        manager = self._conversation_manager()
        now = time.time()
        last = manager.session.last_activity_time if manager is not None else now
        elapsed = max(0.0, now - last)
        if elapsed >= settings.inactivity_timeout_seconds:
            self._end_conversation("Okay. Say Jarvis when you need me.")
            audio_log.log("Conversation inactivity timeout")
            return reminders
        if reminders <= 0 and elapsed >= settings.first_silence_reminder_seconds:
            self.speech.speak("I'm listening.")
            audio_log.log("Conversation first silence reminder")
            return 1
        if reminders == 1 and elapsed >= settings.second_silence_reminder_seconds:
            self.speech.speak("Still here if you want to continue.")
            audio_log.log("Conversation second silence reminder")
            return 2
        return reminders

    def _handle_empty_conversation_transcription(self):
        self._conversation_empty_transcriptions += 1
        audio_log.log(
            "Conversation empty transcription "
            f"{self._conversation_empty_transcriptions}"
        )
        if self._conversation_empty_transcriptions >= 2:
            self._end_conversation(
                "I am having trouble hearing you clearly. Say Jarvis when you need me."
            )
            return True
        self._update_conversation_state(ERROR_RECOVERY, "Empty transcription")
        self.speech.speak("I did not catch that. Please say it again.")
        return False

    def _end_conversation(self, message):
        manager = self._conversation_manager()
        if manager is not None:
            manager.end("exit")
            self.state.update(**manager.snapshot())
        self._update_conversation_state(
            ENDING_CONVERSATION,
            "Returning to wake word mode",
            waiting_for_reply=False,
            recording=False,
        )
        if message:
            self.speech.speak(message)
        audio_log.log("Conversation mode exited")

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
                    audio = self._record_wake_only_followup()
                    if audio.size == 0:
                        self.speech.speak("I didn't hear anything, sir.")
                        continue

                self.state.update(recording=False)
                self.controller._set_state("processing", "Processing command")
                turn = self._do_transcription_and_route(audio)
                if self._activate_conversation_after_turn(turn):
                    self._run_conversation_loop()
            finally:
                self._finish_voice_cycle()

    def _do_transcription_and_route(self, audio, conversation_turn=False):
        if self._stop.is_set():
            return {"text": "", "spoken": "", "exit": False}
        self.state.update(processing=True)
        if conversation_turn:
            self._update_conversation_state(TRANSCRIBING, "Transcribing")
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
            if not conversation_turn:
                self.speech.speak("I didn't catch that, sir.")
                self.controller._set_state("listening_wake", "Listening for Hey Jarvis")
            return {"text": "", "spoken": "", "exit": False}
        
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
                return {"text": text, "spoken": "Confirmed, sir.", "exit": False}
            elif cleaned_text in CANCEL_WORDS:
                gui_controller_instance.resolve_confirmation("cancel_task")
                self.speech.speak("Task cancelled, sir.")
                return {"text": text, "spoken": "Task cancelled, sir.", "exit": False}
            elif cleaned_text in NO_WORDS:
                gui_controller_instance.resolve_confirmation("deny")
                self.speech.speak("Action cancelled, sir.")
                return {"text": text, "spoken": "Action cancelled, sir.", "exit": False}
            else:
                self.speech.speak("Please say yes or no to confirm the action, or cancel to abort.")
                return {
                    "text": text,
                    "spoken": "Please say yes or no to confirm the action, or cancel to abort.",
                    "exit": False,
                }

        if conversation_turn:
            return self._route_conversation_text(text)

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
        return {"text": text, "spoken": spoken or "", "exit": False}

    def _route_conversation_text(self, text):
        manager = self._conversation_manager()
        if manager is None:
            spoken = self.controller.handle_text(text, from_voice=True)
            return {"text": text, "spoken": spoken or "", "exit": False}
        intent = manager.classify(text, self.controller.ctx)
        self.controller._emit("timeline", "conversation_intent", intent.intent_type)
        audio_log.log(f"Conversation intent: {intent.intent_type}")
        if intent.intent_type == INTENT_EXIT:
            self._end_conversation("Okay. Say Jarvis when you need me.")
            return {"text": text, "spoken": "Okay. Say Jarvis when you need me.", "exit": True}
        if intent.uses_tools or (intent.route or {}).get("route_type") == "pending":
            self._update_conversation_state(EXECUTING_TOOL, "Executing task")
            spoken = self.controller.handle_text(text, from_voice=True)
            manager.record_user(text)
            manager.record_tool_result(text, spoken or "")
            if spoken:
                manager.record_assistant(spoken)
            self.state.update(**manager.snapshot())
            return {"text": text, "spoken": spoken or "", "exit": False}
        if intent.intent_type in {
            INTENT_CONVERSATION,
            INTENT_QUESTION,
            INTENT_FOLLOW_UP,
            INTENT_CORRECTION,
        }:
            self._update_conversation_state(THINKING, "Thinking")
            spoken = self.controller.handle_conversation_text(text, from_voice=True)
            return {"text": text, "spoken": spoken or "", "exit": False}
        spoken = self.controller.handle_text(text, from_voice=True)
        return {"text": text, "spoken": spoken or "", "exit": False}

    # ------------------------------------------------------------ recording
    def _record_command(
        self,
        max_seconds=None,
        *,
        start_timeout=5.0,
        silence_timeout=None,
        min_speech_seconds=None,
        speech_start_threshold=None,
        background_noise_threshold=0.0,
        background_noise_filtering=False,
    ):
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
            speech_frames = 0
            start_threshold = max(1, int(speech_start_threshold or 3))
            silence_frames = max(1, int((silence_timeout or 1.4) * 1000 / 30))
            min_frames = max(0, int((min_speech_seconds or 0.0) * 1000 / 30))
            started_deadline = time.monotonic() + max(0.1, float(start_timeout))
            deadline = time.monotonic() + max(0.1, float(max_seconds))
            while time.monotonic() < deadline and not self._stop.is_set():
                frame = self._next_frame(timeout=0.5)
                if frame is None:
                    if not started and time.monotonic() >= started_deadline:
                        return np.array([], dtype=np.int16)
                    continue
                # split CHUNK (1280) into 30ms VAD frames (480) - process subframes
                for sub in self._subframes(frame):
                    pcm = sub.tobytes()
                    voiced = self._subframe_has_voice(
                        sub,
                        background_noise_threshold=background_noise_threshold,
                        background_noise_filtering=background_noise_filtering,
                    )
                    if not started:
                        if voiced:
                            voiced_run += 1
                        else:
                            voiced_run = max(0, voiced_run - 1)
                        if voiced_run >= start_threshold:
                            started = True
                            speech_frames = 1
                            frames.append(pcm)
                        elif time.monotonic() >= started_deadline:
                            return np.array([], dtype=np.int16)
                    else:
                        frames.append(pcm)
                        speech_frames += 1
                        if voiced:
                            silent_run = 0
                        else:
                            silent_run += 1
                            if silent_run >= silence_frames:
                                if speech_frames < min_frames:
                                    return np.array([], dtype=np.int16)
                                return np.frombuffer(b"".join(frames), dtype=np.int16)
            if frames and speech_frames >= min_frames:
                return np.frombuffer(b"".join(frames), dtype=np.int16)
            return np.array([], dtype=np.int16)
        finally:
            self.capture.unsubscribe(self._on_record_frame)

    def _frame_has_voice(self, frame, settings):
        return any(
            self._subframe_has_voice(
                sub,
                background_noise_threshold=getattr(settings, "background_noise_threshold", 0.0),
                background_noise_filtering=getattr(settings, "background_noise_filtering", False),
            )
            for sub in self._subframes(frame)
        )

    def _subframe_has_voice(
        self,
        subframe,
        *,
        background_noise_threshold=0.0,
        background_noise_filtering=False,
    ):
        if background_noise_filtering:
            try:
                level = float(getattr(self.capture, "level", 0.0) or 0.0)
                if level > 0.0 and level < float(background_noise_threshold or 0.0):
                    return False
            except Exception:
                pass
        try:
            return bool(self._listener._vad.is_speech(subframe.tobytes(), SAMPLE_RATE))
        except Exception:
            return False

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
