"""Safe client for an explicitly started, local Colibri API server.

Colibri is intentionally not a JARVIS dependency.  This adapter never starts
processes, downloads models, or calls non-loopback hosts.
"""
from __future__ import annotations

import json
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import Config


class ColibriError(RuntimeError):
    """A disabled, unavailable, or invalid Colibri connection."""


class ColibriAdapter:
    """Text-only adapter for Colibri's documented OpenAI-compatible API."""

    def __init__(self, enabled=None, mode=None, base_url=None, model=None, timeout=None):
        self.enabled = Config.COLIBRI_ENABLED if enabled is None else bool(enabled)
        self.mode = (Config.COLIBRI_MODE if mode is None else mode).strip().lower()
        self.base_url = (Config.COLIBRI_BASE_URL if base_url is None else base_url).rstrip("/")
        self.model = (Config.COLIBRI_MODEL if model is None else model).strip()
        self.timeout = Config.COLIBRI_TIMEOUT_SECONDS if timeout is None else int(timeout)

    @property
    def configured(self) -> bool:
        return self.enabled and self.mode == "http_api"

    def _validate_base_url(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ColibriError("Colibri must use a local HTTP endpoint")

    def _require_configured(self) -> None:
        if not self.enabled:
            raise ColibriError("Colibri is disabled")
        if self.mode != "http_api":
            raise ColibriError("Colibri mode must be http_api")
        self._validate_base_url()

    def _request(self, method: str, endpoint: str, payload=None):
        self._require_configured()
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{endpoint}", data=data, method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # nosec B310: loopback is enforced above
                return json.loads(response.read().decode("utf-8"))
        except (URLError, OSError, ValueError) as exc:
            raise ColibriError(f"Colibri unavailable: {exc}") from exc

    def health(self) -> dict:
        """Return the local server's health payload; never starts a server."""
        return self._request("GET", "/health")

    def complete(self, messages: list[dict], *, max_tokens=512, temperature=0.2) -> str:
        """Submit text-only chat. Returned text is data, never executable actions."""
        if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
            raise ColibriError("messages must be a list of objects")
        response = self._request("POST", "/chat/completions", {
            "model": self.model, "messages": messages, "max_tokens": int(max_tokens),
            "temperature": float(temperature), "stream": False,
        })
        try:
            return str(response["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ColibriError("Colibri returned an invalid completion response") from exc
