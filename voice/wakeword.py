"""
Wake word - fully offline via openwakeword.

openwakeword ships a pre-trained "hey_jarvis" model, so the activation
phrase is "Hey Jarvis". Audio comes from sounddevice (no PyAudio needed).
"""
import threading
from pathlib import Path

import numpy as np

from config import Config

CHUNK = 1280  # 80 ms at 16 kHz - what openwakeword expects


class WakeWordEngine:
    def __init__(self, model_name=None, threshold=None):
        self.model_name = model_name or Config.WAKE_WORD
        self.threshold = (
            threshold if threshold is not None else Config.WAKE_THRESHOLD
        )
        self._model = None
        self._lock = threading.Lock()
        self._predict_lock = threading.Lock()
        self.load_error = ""

    def _candidate_models(self):
        model_name = (self.model_name or "").strip()
        if not model_name:
            return []

        candidates = [model_name]
        if not Path(model_name).suffix and not model_name.endswith("_v0.1"):
            candidates.append(f"{model_name}_v0.1")

        try:
            import openwakeword

            models_dir = (
                Path(openwakeword.__file__).resolve().parent
                / "resources"
                / "models"
            )
            for name in list(candidates):
                for suffix in (".onnx", ".tflite"):
                    resolved = models_dir / f"{name}{suffix}"
                    if resolved.exists():
                        candidates.append(str(resolved))
        except Exception:
            pass

        deduped = []
        seen = set()
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                deduped.append(candidate)
        return deduped

    def _download_missing_models(self):
        try:
            from openwakeword.utils import download_models
        except Exception:
            return False

        base_name = (self.model_name or "").strip()
        if not base_name:
            return False
        if base_name.endswith((".onnx", ".tflite")):
            base_name = Path(base_name).stem

        model_names = [base_name]
        if not base_name.endswith("_v0.1"):
            model_names.append(f"{base_name}_v0.1")
        try:
            download_models(model_names=model_names)
            return True
        except Exception as exc:
            self.load_error = f"Wake-word download failed: {exc}"
            return False

    def _load_model(self):
        from openwakeword.model import Model

        last_error = None
        for candidate in self._candidate_models():
            try:
                try:
                    self._model = Model(
                        wakeword_models=[candidate],
                        inference_framework="onnx",
                    )
                except TypeError:
                    # older openwakeword signature
                    self._model = Model(wakeword_models=[candidate])
                self.load_error = ""
                return True
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise FileNotFoundError(
            f"No openWakeWord model candidate resolved for {self.model_name!r}"
        )

    def _ensure_loaded(self):
        if self._model is not None:
            return True
        with self._lock:
            if self._model is not None:
                return True
            try:
                try:
                    return self._load_model()
                except FileNotFoundError:
                    if not self._download_missing_models():
                        raise
                    return self._load_model()
            except FileNotFoundError as exc:
                self.load_error = f"Wake-word resource missing: {exc}"
                self._model = None
                return False
            except Exception as exc:
                self.load_error = str(exc)
                self._model = None
                return False

    def process(self, audio):
        """Return the current wake-word score for one captured audio frame."""
        if not self._ensure_loaded():
            return 0.0
        frame = np.asarray(audio, dtype=np.int16).reshape(-1)
        try:
            with self._predict_lock:
                prediction = self._model.predict(frame)
        except Exception as exc:
            self.load_error = str(exc)
            return 0.0
        if not isinstance(prediction, dict):
            try:
                return float(prediction)
            except (TypeError, ValueError):
                return 0.0
        score = prediction.get(self.model_name)
        if score is None and prediction:
            score = max(prediction.values())
        try:
            return float(score or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def wait(self, stop_event=None):
        """
        Block until the wake word is heard. Returns True on detection,
        False if stop_event was set or the engine failed to load.
        """
        if not self._ensure_loaded():
            print(f"[wakeword error] {self.load_error}", flush=True)
            return False
        import sounddevice as sd

        try:
            self._model.reset()
        except Exception:
            pass
        with sd.InputStream(
            samplerate=16000, channels=1, dtype="int16", blocksize=CHUNK
        ) as stream:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return False
                data, _ = stream.read(CHUNK)
                audio = np.frombuffer(data, dtype=np.int16)
                try:
                    prediction = self._model.predict(audio)
                except Exception:
                    continue
                score = 0.0
                if isinstance(prediction, dict):
                    score = prediction.get(self.model_name, 0.0)
                    if not score and prediction:
                        score = max(prediction.values())
                if score >= self.threshold:
                    try:
                        self._model.reset()
                    except Exception:
                        pass
                    return True
