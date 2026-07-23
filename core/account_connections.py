"""Real, user-mediated account connection flows for JARVIS settings.

No password, OAuth token, cookie, or QR-code data is stored here. Gmail uses
the existing persistent JARVIS browser profile. WhatsApp uses its official
Desktop client because that is the client used by :mod:`skills.whatsapp`.
The small state file only records a successful verification so capability
health can distinguish an unconnected account from an available one.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone

from config import Config


CONNECTION_FILE = Config.USER_DATA_DIR / "account_connections.json"
ACCOUNT_NAMES = ("gmail", "whatsapp")


# This runs out-of-process with a hard timeout.  UI Automation can occasionally
# stall while a Store application is starting; it must never freeze the GUI or
# JARVIS's command worker.  It reports only connection state, never account
# names, QR contents, cookies, or other private text.
_WHATSAPP_DESKTOP_PROBE = r'''
import json
import ctypes
import re
from ctypes import wintypes

out = {"visible": False, "connected": False, "detail": "WhatsApp Desktop window was not found."}
try:
    # Find matching top-level HWNDs with non-blocking User32 calls and inspect
    # only their non-private title state.
    matches = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _lparam):
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            unread_state = re.match(r"^\(\d+\)\s+whatsapp", title, flags=re.I)
            if ("whatsapp" in title.lower()
                    and (ctypes.windll.user32.IsWindowVisible(hwnd) or unread_state)
                    and not title.lower().startswith("gdi+ window")):
                matches.append((int(hwnd), title))
        return True
    ctypes.windll.user32.EnumWindows(callback_type(collect), 0)
    for handle, title in matches:
        out["visible"] = True
        # An unread-count prefix is top-level, non-private evidence that the
        # client has an active chat session. A plain WhatsApp title proves only
        # that the app is open; never infer login from the process alone.
        if re.match(r"^\(\d+\)\s+whatsapp", title, flags=re.I):
            out["connected"] = True
            out["detail"] = "WhatsApp Desktop signed-in session verified from its unread-count window state."
        else:
            out["detail"] = "WhatsApp Desktop is open, but its signed-in session could not be verified without inspecting private chat content."
        break
except Exception as exc:
    out["detail"] = "WhatsApp Desktop verification could not inspect the application."
print(json.dumps(out))
'''


def _now():
    return datetime.now(timezone.utc).isoformat()


class AccountConnectionManager:
    def __init__(self, ctx=None):
        self.ctx = ctx
        self._lock = threading.RLock()

    @staticmethod
    def _read():
        try:
            raw = json.loads(CONNECTION_FILE.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _write(payload):
        CONNECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONNECTION_FILE.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def status(cls, account):
        account = str(account or "").strip().lower()
        entry = cls._read().get(account, {})
        connected = bool(entry.get("connected"))
        return {
            "account": account,
            "connected": connected,
            "state": "CONNECTED" if connected else "NOT CONNECTED",
            "detail": str(entry.get("detail", "Sign in has not been verified.")),
            "checked_at": str(entry.get("checked_at", "")),
        }

    def _record(self, account, connected, detail, method=""):
        with self._lock:
            payload = self._read()
            payload[account] = {
                "connected": bool(connected),
                "detail": str(detail),
                "checked_at": _now(),
                "method": str(method),
            }
            self._write(payload)
        return self.status(account)

    def begin_login(self, account):
        account = str(account or "").strip().lower()
        if account == "gmail":
            return self._begin_gmail()
        if account == "whatsapp":
            return self._begin_whatsapp()
        return {
            "account": account,
            "connected": False,
            "state": "ERROR",
            "detail": f"Unsupported account: {account}",
            "checked_at": "",
        }

    def verify(self, account):
        account = str(account or "").strip().lower()
        if account == "gmail":
            return self._verify_gmail(open_if_needed=True)
        if account == "whatsapp":
            return self._verify_whatsapp()
        return self.begin_login(account)

    def _browser(self):
        browser = getattr(self.ctx, "browser", None) if self.ctx is not None else None
        if browser is None:
            raise RuntimeError("The JARVIS browser service is unavailable")
        return browser

    def _gmail_page(self, open_if_needed):
        browser = self._browser()
        context = getattr(browser, "_context", None)
        if context is not None:
            for page in reversed(list(getattr(context, "pages", []) or [])):
                url = str(getattr(page, "url", "") or "")
                if "mail.google.com" in url or "accounts.google.com" in url:
                    return page
        if not open_if_needed:
            return None
        return browser.open_site("https://mail.google.com/mail/u/0/#inbox", name="Gmail")

    @staticmethod
    def _gmail_signed_in(page):
        if page is None:
            return False
        url = str(getattr(page, "url", "") or "").lower()
        if "accounts.google.com" in url:
            return False
        if "mail.google.com" not in url:
            return False
        try:
            if page.query_selector("input[type='email'], input[name='identifier']"):
                return False
            # Require Gmail-owned inbox chrome.  A generic ``body`` exists on
            # both signed-in and signed-out mail.google.com pages and used to
            # create a false CONNECTED state before Google login completed.
            return bool(page.query_selector("div[role='main'], div[gh='tm']"))
        except Exception:
            return False

    def _begin_gmail(self):
        try:
            page = self._gmail_page(open_if_needed=True)
        except Exception as exc:
            return self._record("gmail", False, f"Could not open Gmail: {exc}")
        if self._gmail_signed_in(page):
            return self._record("gmail", True, "Gmail session verified in JARVIS browser profile.")
        return self._record(
            "gmail", False,
            "Gmail opened in the JARVIS browser profile. Complete Google sign-in, then click Verify Gmail.",
        )

    def _verify_gmail(self, open_if_needed):
        try:
            page = self._gmail_page(open_if_needed=open_if_needed)
        except Exception as exc:
            return self._record("gmail", False, f"Could not verify Gmail: {exc}")
        if self._gmail_signed_in(page):
            return self._record("gmail", True, "Gmail session verified in JARVIS browser profile.")
        return self._record(
            "gmail", False,
            "Google sign-in is not complete. Finish it in the opened Gmail window and verify again.",
        )

    def _begin_whatsapp(self):
        try:
            os.startfile("whatsapp:")
        except Exception as exc:
            try:
                subprocess.Popen(["explorer.exe", "whatsapp:"], shell=False)
            except Exception:
                return self._record("whatsapp", False, f"Could not open WhatsApp Desktop: {exc}")
        probe = self._probe_whatsapp_desktop()
        if probe["connected"]:
            return self._record("whatsapp", True, probe["detail"], method="desktop")
        return self._record(
            "whatsapp", False,
            "WhatsApp Desktop opened. Complete its official QR-code login, then click Verify WhatsApp.",
            method="desktop",
        )

    def _verify_whatsapp(self):
        probe = self._probe_whatsapp_desktop()
        if probe["connected"]:
            return self._record("whatsapp", True, probe["detail"], method="desktop")
        return self._record("whatsapp", False, probe["detail"], method="desktop")

    @staticmethod
    def _probe_whatsapp_desktop():
        """Return an account-safe Desktop login probe without blocking JARVIS."""
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                [sys.executable, "-c", _WHATSAPP_DESKTOP_PROBE],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                creationflags=creation_flags,
            )
        except Exception as exc:
            return {"visible": False, "connected": False,
                    "detail": f"WhatsApp Desktop verification timed out or failed: {exc}"}
        try:
            payload = json.loads((completed.stdout or "").strip())
            if not isinstance(payload, dict):
                raise ValueError("unexpected probe output")
            return {
                "visible": bool(payload.get("visible")),
                "connected": bool(payload.get("connected")),
                "detail": str(payload.get("detail") or "WhatsApp Desktop could not be verified."),
            }
        except Exception:
            return {"visible": False, "connected": False,
                    "detail": "WhatsApp Desktop could not be verified. Open it, complete QR login, and verify again."}
