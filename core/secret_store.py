"""Small DPAPI-backed store for user-supplied provider secrets.

Secrets deliberately stay outside ``config.json`` so ordinary settings exports,
logs, and support bundles cannot expose an OpenRouter credential.
"""
from __future__ import annotations

from pathlib import Path

from config import Config


_OPENROUTER_SECRET = Config.USER_DATA_DIR / "openrouter.secret"
_DESCRIPTION = "JARVIS OpenRouter API key"


def save_openrouter_key(value: str) -> bool:
    """Protect *value* for the current Windows user with DPAPI."""
    key = str(value or "").strip()
    if not key:
        return False
    try:
        import win32crypt
        _OPENROUTER_SECRET.parent.mkdir(parents=True, exist_ok=True)
        protected = win32crypt.CryptProtectData(
            key.encode("utf-8"), _DESCRIPTION, None, None, None, 0,
        )
        _OPENROUTER_SECRET.write_bytes(protected)
        return True
    except Exception:
        return False


def load_openrouter_key() -> str:
    """Return the current user's unprotected key, or an empty string."""
    try:
        import win32crypt
        if not _OPENROUTER_SECRET.is_file():
            return ""
        _description, raw = win32crypt.CryptUnprotectData(
            _OPENROUTER_SECRET.read_bytes(), None, None, None, 0,
        )
        return raw.decode("utf-8").strip()
    except Exception:
        return ""
