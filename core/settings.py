"""
GUI settings store.

Persists user-facing preferences to %LOCALAPPDATA%\\JARVIS\\config.json.
Secrets (the OpenRouter API key) are NEVER stored or shown here - the key
stays in the environment / .env only.
"""
import json
import threading
from pathlib import Path

from config import Config

SETTINGS_FILE = Config.USER_DATA_DIR / "config.json"

DEFAULTS = {
    "microphone_device": "default",
    "speaker_device": "default",
    "wake_word": Config.WAKE_WORD,
    "wake_threshold": Config.WAKE_THRESHOLD,
    "whisper_model": Config.WHISPER_MODEL,
    "piper_voice": str(Config.PIPER_MODEL),
    "openrouter_model": Config.OPENROUTER_MODEL,
    "browser_preference": "edge",
    "theme": "cinematic",
    "live_typing_speed": 0.02,
    "default_save_behavior": "ask",
    "confirmation_policy": "risk_based",
    "hermes_enabled": Config.HERMES_ENABLED,
    "hermes_provider": Config.HERMES_PROVIDER,
    "hermes_model": Config.HERMES_MODEL or Config.OPENROUTER_MODEL,
    "hermes_mode": Config.HERMES_MODE if Config.HERMES_MODE in {"cli", "disabled"} else "disabled",
    "hermes_concurrency_limit": Config.HERMES_MAX_CONCURRENT_TASKS,
    "hermes_approval_mode": "strict",
    "hermes_background_enabled": False,
    "hermes_schedules_enabled": False,
    "hermes_learning_enabled": False,
    "developer_mode": False,
    "start_voice_automatically": False,
    "start_with_windows": False,
    "minimize_to_tray": True,
    "reduce_motion": False,
    "desktop_folder": str(Config.DESKTOP_PATH),
    "research_folder": str(Config.DATA_DIR / "research"),
    "logs_folder": str(Config.LOG_DIR),
}


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else SETTINGS_FILE
        self._lock = threading.RLock()
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        with self._lock:
            try:
                if self.path.exists():
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        migrated = False
                        merged = dict(DEFAULTS)
                        for key, value in raw.items():
                            if key in merged:
                                merged[key] = value
                        # Repair values left by an older packaged build.
                        # This setting is display/configuration metadata; the
                        # active source runtime always uses Config.PIPER_MODEL.
                        # Do not leave the UI pointing to an old packaged copy.
                        merged["piper_voice"] = str(Config.PIPER_MODEL)
                        if merged.get("openrouter_model") == "moonshotai/kimi-k3":
                            merged["openrouter_model"] = Config.OPENROUTER_MODEL
                            migrated = True
                        if merged.get("hermes_model") in {
                            "moonshotai/kimi-k3", "openai/gpt-oss-120b",
                        }:
                            merged["hermes_model"] = Config.OPENROUTER_MODEL
                            migrated = True
                        # ``managed`` was a presentation-only value that the
                        # adapter never supported.  Never preserve the older
                        # unsafe background default either.
                        if merged.get("hermes_mode") not in {"cli", "disabled"}:
                            merged["hermes_mode"] = "disabled"
                            merged["hermes_enabled"] = False
                            migrated = True
                        if merged.get("hermes_background_enabled") is not False:
                            migrated = True
                        if merged.get("hermes_schedules_enabled") is not False:
                            migrated = True
                        if merged.get("hermes_learning_enabled") is not False:
                            migrated = True
                        if merged.get("hermes_approval_mode") != "strict":
                            migrated = True
                        try:
                            concurrency = int(merged.get("hermes_concurrency_limit", 2))
                        except (TypeError, ValueError):
                            concurrency = 2
                        concurrency = max(1, min(2, concurrency))
                        if merged.get("hermes_concurrency_limit") != concurrency:
                            migrated = True
                        merged["hermes_background_enabled"] = False
                        merged["hermes_schedules_enabled"] = False
                        merged["hermes_learning_enabled"] = False
                        merged["hermes_approval_mode"] = "strict"
                        merged["hermes_concurrency_limit"] = concurrency
                        self._data = merged
                        if migrated:
                            self.save()
            except Exception:
                self._data = dict(DEFAULTS)
            return dict(self._data)

    def save(self):
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    json.dumps(self._data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return True
            except Exception:
                return False

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key, value):
        if key not in DEFAULTS:
            raise KeyError(f"Unknown setting: {key}")
        with self._lock:
            self._data[key] = value
        return True

    def update(self, mapping):
        with self._lock:
            for key, value in dict(mapping).items():
                if key in DEFAULTS:
                    self._data[key] = value
        return self.save()

    def as_dict(self):
        with self._lock:
            return dict(self._data)
