"""
Session Registry — the central record of EVERYTHING JARVIS opens.

Every skill that opens an app, window, browser tab, document or browser
registers it here. That is what powers:
    "close it" / "close that"          -> most recent entry
    "close YouTube" / "close Word"     -> fuzzy name match
    "close everything you opened"      -> reverse-order teardown

Serializable fields are persisted to data/session_registry.json so the
registry survives restarts for anything still closable (PIDs, window
titles). Live objects (Playwright pages, COM closers) are memory-only.
"""
import json
import threading
import time
import uuid
from difflib import get_close_matches
from pathlib import Path


def _native_window_closed(user32, hwnd):
    """A hidden AppFrame is closed even if Windows retains its host HWND."""
    return (
        not bool(user32.IsWindow(int(hwnd)))
        or not bool(user32.IsWindowVisible(int(hwnd)))
    )


class SessionRegistry:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.session_id = uuid.uuid4().hex
        self._entries = []          # list of dicts, oldest -> newest
        self._runtime = {}          # id -> {"page": Page, "closer": callable}
        self._load()

    # ------------------------------------------------------------------ io
    def _load(self):
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._entries = [
                        entry for entry in data
                        if entry.get("runtime_session_id") == self.session_id
                    ]
        except Exception:
            self._entries = []

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._entries, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ------------------------------------------------------------ register
    def register(self, type_, name, pid=None, window_title=None,
                 page=None, closer=None, extra=None, hwnd=None,
                 exe_path=None, path=None, state="open"):
        """
        type_: app | window | browser_tab | browser | document | folder
        page:  live Playwright Page object (memory only)
        closer: zero-arg callable that closes the thing (memory only)
        hwnd:  native window handle when available
        exe_path: executable path when available
        path:  file / folder path when applicable
        state: current lifecycle state (open | closed | minimized ...)
        """
        with self._lock:
            merged_extra = dict(extra) if extra else {}
            if exe_path is not None:
                merged_extra.setdefault("exe_path", str(exe_path))
            if path is not None:
                merged_extra.setdefault("path", str(path))
            session_id = uuid.uuid4().hex[:12]
            process_name = merged_extra.get("process_name")
            entry = {
                "id": session_id,
                "session_id": session_id,
                "runtime_session_id": getattr(self, "session_id", "test-session"),
                "type": type_,
                "resource_type": type_,
                "name": str(name),
                "display_name": str(name),
                "pid": pid,
                "process_name": process_name,
                "window_title": window_title,
                "hwnd": hwnd,
                "window_handle": hwnd,
                "executable_path": str(exe_path) if exe_path is not None else None,
                "file_path": str(path) if path is not None and type_ in ("file", "document") else None,
                "folder_path": str(path) if path is not None and type_ == "folder" else None,
                "browser_session": merged_extra.get("browser_session"),
                "browser_tab": merged_extra.get("browser_tab"),
                "state": state,
                "opened_at": time.time(),
                "opened_by_jarvis": True,
                "unsaved_state": merged_extra.get("unsaved", "unknown"),
                "close_policy": merged_extra.get("close_policy", "owned_only"),
            }
            if merged_extra:
                entry["extra"] = {k: str(v) for k, v in merged_extra.items()}
            self._entries.append(entry)
            if page is not None or closer is not None:
                self._runtime[entry["id"]] = {
                    "thread_id": threading.get_ident(),
                }
                if page is not None:
                    self._runtime[entry["id"]]["page"] = page
                if closer is not None:
                    self._runtime[entry["id"]]["closer"] = closer
            self._save()
            return entry

    def open_item(self, type_, name, **kwargs):
        """Compatibility alias used by skills and external integrations."""
        return self.register(type_, name, **kwargs)

    def unregister(self, entry_id):
        with self._lock:
            self._entries = [e for e in self._entries if e["id"] != entry_id]
            self._runtime.pop(entry_id, None)
            self._save()

    def set_state(self, entry_id, state):
        """Update the lifecycle state of a tracked entry (open/minimized/...)."""
        with self._lock:
            for entry in self._entries:
                if entry["id"] == entry_id:
                    entry["state"] = state
                    break
            self._save()

    def update_entry(self, entry_id, **fields):
        """Update serializable ownership metadata for an existing entry."""
        allowed = {
            "name", "display_name", "window_title", "hwnd", "window_handle",
            "state", "unsaved_state", "close_policy", "file_path", "folder_path",
        }
        with self._lock:
            for entry in self._entries:
                if entry["id"] == entry_id:
                    for key, value in fields.items():
                        if key in allowed:
                            entry[key] = value
                    break
            self._save()

    def count_open(self):
        with self._lock:
            return sum(1 for e in self._entries if self._still_alive(e))

    # -------------------------------------------------------------- queries
    def list_open(self):
        with self._lock:
            return [self._enrich(e) for e in self._entries]

    def most_recent(self):
        with self._lock:
            live = [e for e in self._entries if self._still_alive(e)]
            return self._enrich(live[-1]) if live else None

    def find_by_name(self, name):
        """Fuzzy match owned entries by resource and application aliases."""
        if not name:
            return []
        name_l = name.lower().strip()
        with self._lock:
            candidates = [e for e in self._entries if self._still_alive(e)]
        # 1) substring match
        def aliases(entry):
            extra = entry.get("extra") or {}
            values = (
                entry.get("name"), entry.get("display_name"),
                entry.get("window_title"), entry.get("process_name"),
                entry.get("executable_path"), extra.get("application"),
                extra.get("process_name"),
            )
            return [str(value).lower() for value in values if value]

        hits = [e for e in candidates if any(name_l in value for value in aliases(e))]
        if hits:
            return [self._enrich(e) for e in hits]
        # 2) difflib fuzzy match
        names = {}
        for entry in candidates:
            for alias in aliases(entry):
                names.setdefault(alias, entry)
        close = get_close_matches(name_l, list(names), n=3, cutoff=0.45)
        seen = set()
        matched = []
        for alias in close:
            entry = names[alias]
            if entry["id"] not in seen:
                seen.add(entry["id"])
                matched.append(self._enrich(entry))
        return matched

    def _enrich(self, entry):
        e = dict(entry)
        rt = self._runtime.get(e["id"], {})
        e["_page"] = rt.get("page")
        e["_closer"] = rt.get("closer")
        return e

    def _still_alive(self, entry):
        current_session = getattr(self, "session_id", None)
        entry_session = entry.get("runtime_session_id")
        if current_session is not None and entry_session != current_session:
            return False
        rt = self._runtime.get(entry["id"], {})
        page = rt.get("page")
        if page is not None:
            if rt.get("thread_id") not in (None, threading.get_ident()):
                return entry.get("state", "open") != "closed"
            try:
                if page.is_closed():
                    return False
            except Exception:
                return False
        pid = entry.get("pid")
        if pid:
            try:
                import psutil
                return psutil.pid_exists(int(pid))
            except Exception:
                return True
        return True

    # -------------------------------------------------------------- closing
    def close_most_recent(self):
        with self._lock:
            live = [e for e in self._entries if self._still_alive(e)]
            if not live:
                return None
            entry = live[-1]
            ok = self._close_entry(entry)
            if ok:
                self._remove(entry["id"])
            return {"entry": self._enrich(entry), "closed": ok}

    def close_recent(self):
        """Compatibility alias for the most recently opened live item."""
        return self.close_most_recent()

    def get_status(self):
        """Return a serializable snapshot of currently tracked items."""
        return [
            {key: value for key, value in entry.items() if not key.startswith("_")}
            for entry in self.list_open()
        ]

    def close_by_name(self, name):
        results = []
        for entry in self.find_by_name(name):
            ok = self._close_entry(entry)
            if ok:
                self._remove(entry["id"])
            results.append({"entry": self._enrich(entry), "closed": ok})
        return results

    def close_all(self):
        results = []
        with self._lock:
            live = [e for e in self._entries if self._still_alive(e)]
        for entry in reversed(live):          # newest first
            ok = self._close_entry(entry)
            if ok:
                self._remove(entry["id"])
            results.append({"entry": self._enrich(entry), "closed": ok})
        return results

    def discard_types(self, resource_types):
        """Forget already-closed runtime resources without invoking closers."""
        wanted = {str(item) for item in resource_types}
        with self._lock:
            removed = [
                entry for entry in self._entries
                if entry.get("runtime_session_id") == self.session_id
                and entry.get("type") in wanted
            ]
            removed_ids = {entry["id"] for entry in removed}
            self._entries = [
                entry for entry in self._entries if entry["id"] not in removed_ids
            ]
            for entry_id in removed_ids:
                self._runtime.pop(entry_id, None)
            self._save()
        return len(removed)

    def _remove(self, entry_id):
        with self._lock:
            self._entries = [e for e in self._entries if e["id"] != entry_id]
            self._runtime.pop(entry_id, None)
            self._save()

    def _close_entry(self, entry):
        rt = self._runtime.get(entry["id"], {})

        if entry.get("close_policy") == "unverified_ownership":
            return False

        # 1) custom closer (COM objects, special cases)
        closer = rt.get("closer")
        if closer is not None:
            try:
                closer()
                return True
            except Exception:
                pass

        # 2) Playwright page / tab
        page = rt.get("page")
        if page is not None:
            try:
                if not page.is_closed():
                    page.close()
                return True
            except Exception:
                pass

        # 3) native window handle (preferred for Explorer ownership)
        hwnd = entry.get("hwnd") or entry.get("window_handle")
        if hwnd:
            try:
                import ctypes
                WM_CLOSE = 0x0010
                user32 = ctypes.windll.user32
                if user32.IsWindow(int(hwnd)):
                    user32.PostMessageW(int(hwnd), WM_CLOSE, 0, 0)
                    import time
                    deadline = time.time() + 3.0
                    while (time.time() < deadline
                           and not _native_window_closed(user32, hwnd)):
                        time.sleep(0.05)
                    return _native_window_closed(user32, hwnd)
            except Exception:
                pass

        # 4) kill by PID
        pid = entry.get("pid")
        if pid:
            try:
                import psutil
                proc = psutil.Process(int(pid))
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
                return True
            except Exception:
                pass

        # 5) close by window title
        title = entry.get("window_title") or entry.get("name")
        if title:
            try:
                import pygetwindow as gw
                wins = gw.getWindowsWithTitle(title)
                if wins:
                    wins[0].close()
                    return True
            except Exception:
                pass

        # 6) last resort: kill by process name
        try:
            import psutil
            target = (entry.get("name") or "").lower().replace(".exe", "")
            for proc in psutil.process_iter(["name"]):
                pname = (proc.info.get("name") or "").lower().replace(".exe", "")
                if target and target in pname:
                    proc.terminate()
                    return True
        except Exception:
            pass
        return False
