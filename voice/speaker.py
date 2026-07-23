"""Offline Piper text-to-speech and local ``sounddevice`` playback.

Piper is the sole production speech engine. Playback uses the already required
sounddevice/PortAudio stack instead of pygame, which has no compatible wheel
for the Python 3.14 runtime used by the live JARVIS launcher.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
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
        self._piper_process_lock = threading.RLock()
        self._piper_process = None
        self._piper_messages = None
        self._piper_reader = None
        self._piper_worker_dir = Path(Config.TEMP_DIR) / "piper_worker"
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
        # PortAudio discovery imports native modules and queries Windows audio.
        # Defer it until settings are applied or speech is first requested so
        # constructing the desktop backend cannot hold first paint hostage.

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
        # Piper's native synthesis can hold the caller until an utterance is
        # complete.  It runs in an external persistent worker so cancellation
        # can terminate only that owned worker without freezing Qt or touching
        # the microphone.  Keep an idle worker warm between utterances.
        if self._speaking.is_set():
            self._terminate_piper_worker()
        with self._playback_lock:
            stream = self._output_stream
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass

    def close(self):
        """Cancel speech and release the owned persistent Piper process."""
        self._stop.set()
        self._terminate_piper_worker()
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
            audio_log.log("Piper playback starting")
            self._play_wav(tmp_path)
            if not self._should_stop():
                audio_log.log("Piper playback completed")
        except InterruptedError:
            return
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
            executable = self._piper_executable()
            if executable is None:
                # Development-only compatibility when the official CLI entry
                # point is absent.  Verified source and packaged builds both
                # include piper.exe and therefore never use this blocking path.
                if self._piper_voice is None:
                    from piper import PiperVoice
                    self._piper_voice = PiperVoice.load(model_path)
                with wave.open(str(path), "wb") as wav_file:
                    self._piper_voice.synthesize_wav(text, wav_file)
                return

            # PyInstaller's windowed bootloader supplies different inherited
            # standard-handle semantics than python.exe.  A long-lived child
            # can consequently wait forever for a line that was flushed by
            # the frozen parent.  One bounded process per frozen utterance
            # closes stdin deterministically (EOF) while synthesis remains
            # off the GUI thread and fully cancellable through the owned PID.
            if getattr(sys, "frozen", False):
                self._synth_piper_frozen(text, path, executable, model_path)
                return

            self._start_piper_worker(executable, model_path)
            with self._piper_process_lock:
                process = self._piper_process
                messages = self._piper_messages
            if process is None or process.stdin is None or messages is None:
                raise RuntimeError("Piper worker did not start")

            while True:
                try:
                    messages.get_nowait()
                except queue.Empty:
                    break

            try:
                process.stdin.write(str(text).replace("\n", " ") + "\n")
                process.stdin.flush()
                audio_log.log("Piper synthesis request sent to external worker")
            except (BrokenPipeError, OSError) as exc:
                self._terminate_piper_worker()
                raise RuntimeError(f"Piper worker input failed: {exc}") from exc

            deadline = time.monotonic() + 120.0
            detail = ""
            observed_files = {}
            while time.monotonic() < deadline:
                if self._should_stop():
                    self._terminate_piper_worker()
                    raise InterruptedError("Piper synthesis cancelled")
                try:
                    message = messages.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None:
                        self._terminate_piper_worker()
                        raise RuntimeError(
                            detail or f"Piper worker exited with code {process.returncode}"
                        )
                    generated = self._completed_worker_file(observed_files)
                    if generated is not None:
                        if self._collect_worker_file(generated, path):
                            audio_log.log("Piper audio collected from external worker")
                            return
                    continue
                detail = message or detail
                match = re.search(r"Wrote\s+(.+\.wav)\s*$", message)
                if match is None:
                    continue
                generated = Path(match.group(1).strip())
                if self._collect_worker_file(generated, path):
                    audio_log.log("Piper audio collected from external worker")
                    return

            self._terminate_piper_worker()
            raise RuntimeError("Piper synthesis timed out")

    def _synth_piper_frozen(self, text, path, executable, model_path):
        self._piper_worker_dir.mkdir(parents=True, exist_ok=True)
        for stale in self._piper_worker_dir.glob("*.wav"):
            try:
                stale.unlink()
            except OSError:
                pass
        input_fd, input_raw = tempfile.mkstemp(
            prefix="jarvis_piper_input_", suffix=".txt",
            dir=str(self._piper_worker_dir), text=True,
        )
        os.close(input_fd)
        input_path = Path(input_raw)
        input_path.write_text(
            str(text).replace("\n", " ") + "\n", encoding="utf-8"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            [
                str(executable), "--model", str(model_path),
                "--input-file", str(input_path),
                "--output-dir", str(self._piper_worker_dir),
                "--output-dir-naming", "timestamp",
            ],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        with self._piper_process_lock:
            self._piper_process = process
            self._piper_messages = None
            self._piper_reader = None
        audio_log.log(
            f"Piper frozen worker started (pid={getattr(process, 'pid', 'unknown')})"
        )
        try:
            _stdout, stderr = process.communicate(timeout=120)
        except subprocess.TimeoutExpired as exc:
            self._terminate_piper_worker()
            raise RuntimeError("Piper frozen synthesis timed out") from exc
        finally:
            with self._piper_process_lock:
                if self._piper_process is process:
                    self._piper_process = None
            try:
                input_path.unlink(missing_ok=True)
            except OSError:
                pass
        if self._should_stop():
            raise InterruptedError("Piper synthesis cancelled")
        if process.returncode:
            detail = str(stderr or "").strip()
            raise RuntimeError(detail[-500:] or f"Piper worker exited with code {process.returncode}")

        match = re.search(r"Wrote\s+(.+\.wav)\s*$", str(stderr or ""), re.MULTILINE)
        generated = Path(match.group(1).strip()) if match else None
        if generated is None or not generated.is_file():
            candidates = sorted(
                self._piper_worker_dir.glob("*.wav"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            generated = candidates[0] if candidates else None
        if generated is None or not self._collect_worker_file(generated, path):
            raise RuntimeError("Piper frozen worker returned no completed audio")
        audio_log.log("Piper audio collected from frozen worker")

    def _completed_worker_file(self, observed):
        """Find a closed, stable WAV even if Piper's log reader is delayed."""
        now = time.monotonic()
        try:
            candidates = tuple(self._piper_worker_dir.glob("*.wav"))
        except OSError:
            return None
        for candidate in candidates:
            try:
                size = candidate.stat().st_size
            except OSError:
                continue
            previous = observed.get(candidate)
            observed[candidate] = (size, now)
            if size <= 44 or previous is None or previous[0] != size:
                continue
            if now - previous[1] < 0.05:
                continue
            try:
                with wave.open(str(candidate), "rb") as wav_file:
                    if wav_file.getnframes() <= 0:
                        continue
            except (OSError, EOFError, wave.Error):
                continue
            return candidate
        return None

    def _collect_worker_file(self, generated, path):
        generated = Path(generated)
        try:
            if generated.resolve().parent != self._piper_worker_dir.resolve():
                raise RuntimeError("Piper worker returned an unexpected output path")
            path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(generated, path)
        except OSError as exc:
            # Piper writes WAV chunks incrementally.  A stable size and valid
            # header do not prove its Windows file handle is closed; sharing
            # violations are a normal "not ready yet" signal.
            if getattr(exc, "winerror", None) in {32, 33}:
                return False
            raise RuntimeError(f"Unable to collect Piper audio: {exc}") from exc
        return True

    @staticmethod
    def _piper_executable():
        candidates = []
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            candidates.append(Path(frozen_root) / "piper.exe")
        candidates.extend([
            Path(sys.executable).with_name("piper.exe"),
            Path(sys.executable).resolve().parent / "Scripts" / "piper.exe",
        ])
        located = shutil.which("piper")
        if located:
            candidates.append(Path(located))
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate.resolve()
            except OSError:
                continue
        return None

    def _start_piper_worker(self, executable, model_path):
        with self._piper_process_lock:
            process = self._piper_process
            if process is not None and process.poll() is None:
                return
            self._piper_worker_dir.mkdir(parents=True, exist_ok=True)
            for stale in self._piper_worker_dir.glob("*.wav"):
                try:
                    stale.unlink()
                except OSError:
                    pass
            messages = queue.Queue()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            process = subprocess.Popen(
                [
                    str(executable), "--model", str(model_path),
                    "--output-dir", str(self._piper_worker_dir),
                    "--output-dir-naming", "timestamp",
                ],
                shell=False,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=flags,
            )
            self._piper_process = process
            self._piper_messages = messages
            audio_log.log(
                f"Piper external worker started (pid={getattr(process, 'pid', 'unknown')})"
            )

            def read_messages():
                stderr = process.stderr
                if stderr is None:
                    return
                for line in stderr:
                    messages.put(line.strip())

            reader = threading.Thread(
                target=read_messages,
                daemon=True,
                name="jarvis-piper-messages",
            )
            self._piper_reader = reader
            reader.start()

    def _terminate_piper_worker(self):
        with self._piper_process_lock:
            process = self._piper_process
            self._piper_process = None
            self._piper_messages = None
            self._piper_reader = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass

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
