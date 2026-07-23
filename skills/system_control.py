"""
Universal Open/Close & System Control.

"open X" resolution order:
  (a) installed app  — common-app map, then fuzzy Start Menu shortcuts
  (b) file by name   — search Desktop + Documents
  (c) folder path
  (d) website        — contains a dot or matches the known-site map
  (e) ask for clarification

"close X" goes through the Session Registry, with pygetwindow and psutil
as fallbacks. Plus volume (pycaw), screenshot, lock, shutdown (confirmed),
battery/status report.
"""
import ctypes
import os
import re
import subprocess
import time
from difflib import get_close_matches, SequenceMatcher
from pathlib import Path
from types import SimpleNamespace

from config import Config
from skills.browser import KNOWN_SITES
from skills.windows_targets import resolve_windows_target

# ---------------------------------------------------------------------------
# Well-known applications (name -> launch spec)
# ---------------------------------------------------------------------------
COMMON_APPS = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "cmd": ["cmd.exe"],
    "command prompt": ["cmd.exe"],
    "terminal": ["wt.exe"],
    "windows terminal": ["wt.exe"],
    "powershell": ["powershell.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "task manager": ["taskmgr.exe"],
    "control panel": ["control.exe"],
    "settings": ["ms-settings:"],
    "snipping tool": ["SnippingTool.exe"],
    "word": ["winword"],
    "excel": ["excel"],
    "powerpoint": ["powerpnt"],
    "chrome": ["chrome"],
    "edge": ["msedge"],
    "firefox": ["firefox"],
    "spotify": ["spotify"],
    "vscode": ["code"],
    "vs code": ["code"],
    "visual studio code": ["code"],
    "whatsapp": ["whatsapp:"],
    "telegram": ["telegram:"],
    "vlc": ["vlc"],
    "obs": ["obs64"],
    "steam": ["steam:"],
    "discord": ["discord:"],
}

START_MENU_DIRS = [
    Path(os.environ.get(
        "PROGRAMDATA",
        Path(os.environ.get("SystemDrive", "C:")) / "ProgramData",
    ))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("APPDATA", ""))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs",
]

SEARCH_DIRS = [Config.DESKTOP_PATH, Path.home() / "Documents"]


def _background_process_kwargs():
    """Hide only helper shells; explicitly requested terminals stay visible."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return {"creationflags": flags} if flags else {}


# ---------------------------------------------------------------------------
# OPEN
# ---------------------------------------------------------------------------
def _start_menu_shortcuts():
    links = {}
    for d in START_MENU_DIRS:
        try:
            if d.exists():
                for lnk in d.rglob("*.lnk"):
                    links[lnk.stem.lower()] = lnk
        except Exception:
            continue
    return links


def _search_files(name):
    """Find a file by fuzzy name on Desktop + Documents."""
    name_l = name.lower()
    best = None
    best_score = 0.0
    for base in SEARCH_DIRS:
        try:
            if not base.exists():
                continue
            for p in base.rglob("*"):
                if not p.is_file():
                    continue
                stem = p.stem.lower()
                if name_l == stem or name_l in stem:
                    return p
                score = SequenceMatcher(None, name_l, stem).ratio()
                if score > best_score and score >= 0.6:
                    best, best_score = p, score
        except Exception:
            continue
    return best


def _launch_app(name, ctx):
    spec = COMMON_APPS.get(name.lower())
    if not spec:
        return None
    target = spec[0]
    try:
        if target.endswith(":"):                      # URI scheme (settings:, whatsapp:)
            os.startfile(target)
            return {"pid": None, "how": "uri"}
        if target.lower() in {"cmd.exe", "powershell.exe", "wt.exe"}:
            proc = subprocess.Popen([target], shell=False)
            return {"pid": proc.pid, "how": "interactive_terminal"}
        proc = subprocess.Popen(
            [target], shell=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_background_process_kwargs(),
        )
        return {"pid": proc.pid, "how": "direct"}
    except Exception:
        try:
            subprocess.Popen(
                f"start \"\" \"{target}\"", shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                **_background_process_kwargs(),
            )
            return {"pid": None, "how": "start"}
        except Exception:
            return None


def _matching_process_ids(executable):
    """Return live PIDs for an executable name without trusting a launcher."""
    try:
        import psutil
        wanted = Path(str(executable)).name.lower()
        return {
            int(process.info["pid"])
            for process in psutil.process_iter(("pid", "name"))
            if str(process.info.get("name") or "").lower() == wanted
        }
    except Exception:
        return set()


def _process_create_time(pid):
    """Capture an exact process identity for later owned-only cleanup."""
    try:
        import psutil
        return float(psutil.Process(int(pid)).create_time())
    except Exception:
        return None


def _window_pid(hwnd):
    if not hwnd:
        return None
    try:
        process_id = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(
            int(hwnd), ctypes.byref(process_id)
        )
        return int(process_id.value) or None
    except Exception:
        return None


def _native_window_visible(hwnd):
    """Reject hidden launcher/IME windows during ownership verification."""
    if not hwnd or os.name != "nt":
        return bool(hwnd)
    try:
        user32 = ctypes.windll.user32
        return bool(user32.IsWindow(int(hwnd)) and user32.IsWindowVisible(int(hwnd)))
    except Exception:
        return False


def _native_process_name(pid):
    """Return a process image basename without importing process libraries.

    Folder launch verification runs while background capability discovery may
    still be importing optional packages.  Importing ``psutil`` on this hot
    path can therefore wait behind Python's import lock for an unrelated slow
    health probe.  QueryFullProcessImageName is sufficient to prove that a
    newly created window belongs to Windows Explorer and does not execute or
    terminate anything.
    """
    if os.name != "nt" or not pid:
        return ""
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(
        process_query_limited_information, False, int(pid),
    )
    if not handle:
        return ""
    try:
        capacity = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(capacity.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(capacity),
        ):
            return ""
        return Path(buffer.value).name.lower()
    finally:
        kernel32.CloseHandle(handle)


def _native_process_ids_by_name(executable):
    """Snapshot matching Windows PIDs without importing process libraries."""
    if os.name != "nt":
        return _matching_process_ids(executable)
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if not snapshot or snapshot == invalid_handle:
        return set()
    wanted = Path(str(executable)).name.lower()
    matches = set()
    entry = ProcessEntry32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                if entry.szExeFile.lower() == wanted:
                    matches.add(int(entry.th32ProcessID))
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return matches


def _effective_window_pid(hwnd, fallback_pid=None):
    """Resolve the dedicated app PID behind a hosted top-level window.

    Store applications place a visible ``ApplicationFrameWindow`` in the
    shared ApplicationFrameHost process while the real application owns a
    visible ``Windows.UI.Core.CoreWindow`` child. Tracking the shared host
    makes safe close verification impossible, so unwrap only this documented
    hosted-window shape and retain the top-level HWND for exact closing.
    """
    if os.name != "nt" or not hwnd:
        return fallback_pid
    if _native_process_name(fallback_pid).lower() != "applicationframehost.exe":
        return fallback_pid
    from ctypes import wintypes

    candidates = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM,
    )

    def visit(child, _parameter):
        if ctypes.windll.user32.IsWindowVisible(child):
            child_pid = _window_pid(child)
            if child_pid and child_pid != fallback_pid:
                class_buffer = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetClassNameW(child, class_buffer, 256)
                candidates.append((child_pid, class_buffer.value))
        return True

    callback = callback_type(visit)
    ctypes.windll.user32.EnumChildWindows(int(hwnd), callback, 0)
    for child_pid, class_name in candidates:
        if class_name == "Windows.UI.Core.CoreWindow":
            return child_pid
    return fallback_pid


def _verify_launched_app(target, existing_hwnds, existing_pids, timeout=7.0):
    """Resolve the real surviving GUI window after Windows launch redirection.

    Store-backed apps such as modern Notepad can spawn through a short-lived
    launcher PID.  Ownership is therefore established from a new top-level
    window and its real PID, never from the initial process alone.
    """
    try:
        import pygetwindow as gw
    except Exception:
        return None

    executable = Path(str(target.value)).name.lower()
    target_words = {
        word for word in re.findall(r"[a-z0-9]+", str(target.name).lower())
        if len(word) > 2 and word not in {"microsoft", "google", "application"}
    }
    deadline = time.time() + max(0.1, float(timeout))
    hosted_frame_grace_deadline = None
    fallback_candidate = None
    while time.time() < deadline:
        matching_pids = _matching_process_ids(executable)
        new_process_ids = matching_pids.difference(existing_pids)
        candidates = []
        for window in gw.getAllWindows():
            title = str(getattr(window, "title", "") or "").strip()
            hwnd = getattr(window, "_hWnd", None)
            if (not title or not hwnd or hwnd in existing_hwnds
                    or not _native_window_visible(hwnd)):
                continue
            host_pid = _window_pid(hwnd)
            pid = _effective_window_pid(hwnd, host_pid)
            hosted_frame = (
                _native_process_name(host_pid).lower() == "applicationframehost.exe"
                and pid != host_pid
            )
            # A Store frame becomes visible slightly before its real app
            # CoreWindow is attached. Keep polling rather than recording the
            # shared host as the application owner.
            if (_native_process_name(host_pid).lower() == "applicationframehost.exe"
                    and pid == host_pid):
                continue
            title_low = title.lower()
            title_matches = bool(target_words) and any(
                word in title_low for word in target_words
            )
            if title_matches or pid in new_process_ids:
                candidates.append((pid, int(hwnd), title, hosted_frame))
        if candidates:
            # Prefer a window owned by a newly observed real process.  A title
            # match remains valid when the app reuses an existing process.
            # Store apps expose both an internal CoreWindow and the visible
            # ApplicationFrameHost. Keep the real child PID for ownership but
            # retain the host-frame HWND that actually responds to window
            # state commands.
            candidates.sort(key=lambda item: (
                item[0] not in new_process_ids,
                not item[3],
            ))
            pid, hwnd, title, hosted_frame = candidates[0]
            if not hosted_frame:
                actual_process = _native_process_name(pid).lower()
                if actual_process and executable and actual_process != executable:
                    fallback_candidate = (pid, hwnd, title)
                    now = time.time()
                    if hosted_frame_grace_deadline is None:
                        hosted_frame_grace_deadline = min(deadline, now + 1.0)
                    if now < hosted_frame_grace_deadline:
                        time.sleep(0.05)
                        continue
            return pid, hwnd, title
        time.sleep(0.1)
    return fallback_candidate


def _find_new_folder_window(path, existing_hwnds, timeout=10.0):
    """Return the real Explorer PID/HWND created for a folder request."""
    deadline = time.time() + max(0.1, float(timeout))
    while time.time() < deadline:
        new_windows = [
            (hwnd, pid, title)
            for hwnd, pid, title in _native_window_snapshot()
            if hwnd not in existing_hwnds
        ]
        matches = [
            window for window in new_windows
            if path.name.lower() in window[2].lower()
        ]
        if matches:
            hwnd, pid, title = matches[-1]
            return pid, hwnd, title
        # Explorer often creates the verified window under the generic title
        # "File Explorer" and updates it to the destination later. A new HWND
        # owned by explorer.exe is still strong ownership evidence for the
        # request JARVIS just issued.  Verify the owning process natively so
        # this path cannot block on a lazy psutil import during startup scans.
        explorer_matches = []
        for hwnd, pid, title in new_windows:
            if _native_process_name(pid) == "explorer.exe":
                explorer_matches.append((pid, hwnd, title))
        if explorer_matches:
            return explorer_matches[-1]
        time.sleep(0.1)
    return None


def _native_window_snapshot():
    """Enumerate visible titled windows with bounded native Win32 calls.

    ``pygetwindow.getAllWindows`` can block behind shell accessibility state
    while Explorer is opening a folder.  Folder ownership needs only HWND,
    PID, visibility, and title, all of which EnumWindows provides directly.
    """
    if os.name != "nt":
        return []
    from ctypes import wintypes

    windows = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM,
    )

    def visit(hwnd, _parameter):
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if title:
            windows.append((int(hwnd), _window_pid(hwnd), title))
        return True

    callback = callback_type(visit)
    ctypes.windll.user32.EnumWindows(callback, 0)
    return windows


def _launch_resolved(target, ctx):
    if target.kind in ("folder", "file"):
        path = Path(target.value)
        if not path.exists():
            return None
        dedicated_process = False
        process_create_time = None
        try:
            if target.kind == "folder":
                existing_explorer_pids = _native_process_ids_by_name("explorer.exe")
                existing_hwnds = {
                    hwnd for hwnd, _pid, _title in _native_window_snapshot()
                }
                # Explorer hands this request to the user's existing shell and
                # the short-lived launcher may exit immediately. Popen itself
                # is asynchronous, so a busy shell cannot hold the serialized
                # command worker inside ShellExecute for a full DDE timeout.
                # Ownership is established only from the new real HWND below.
                subprocess.Popen(
                    ["explorer.exe", str(path)], shell=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    **_background_process_kwargs(),
                )
                verified = _find_new_folder_window(path, existing_hwnds)
                if verified is None:
                    return None
                pid, hwnd, window_title = verified
                dedicated_process = bool(pid and pid not in existing_explorer_pids)
                process_create_time = (
                    _process_create_time(pid) if dedicated_process else None
                )
            else:
                os.startfile(str(path))
                pid = None
                hwnd = None
                window_title = path.name or str(path)
            ctx.registry.register(
                target.kind, path.name or str(path),
                pid=pid, hwnd=hwnd, window_title=window_title, path=str(path),
                extra={
                    "path": str(path),
                    "process_name": "explorer.exe" if target.kind == "folder" else "",
                    "close_policy": (
                        "owned_only" if hwnd or pid
                        else "unverified_ownership"
                    ),
                    "cleanup_pid_after_window_close": dedicated_process,
                    "process_create_time": (
                        process_create_time if process_create_time is not None else ""
                    ),
                },
            )
            return f"Opening the {target.kind} {path.name or path}."
        except OSError:
            return None
    if target.kind == "app":
        try:
            existing_hwnds = set()
            try:
                import pygetwindow as gw
                existing_hwnds = {
                    getattr(window, "_hWnd", None) for window in gw.getAllWindows()
                    if getattr(window, "_hWnd", None)
                }
            except Exception:
                pass
            existing_pids = _matching_process_ids(target.value)
            existing_window_pids = {
                pid for pid in (
                    _effective_window_pid(hwnd, _window_pid(hwnd))
                    for hwnd in existing_hwnds
                ) if pid
            }
            proc = subprocess.Popen([target.value], shell=False,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    **_background_process_kwargs())
            verified = _verify_launched_app(
                target, existing_hwnds, existing_pids,
            )
            if verified is None:
                return None
            pid, hwnd, window_title = verified
            actual_process_name = _native_process_name(pid) or Path(target.value).name
            terminate_pid_on_close = (
                pid not in existing_pids
                and pid not in existing_window_pids
                and actual_process_name.lower() != "applicationframehost.exe"
            )
            ctx.registry.register("app", target.name, pid=pid, hwnd=hwnd,
                                  window_title=window_title,
                                  exe_path=target.value,
                                  extra={
                                      "process_name": actual_process_name,
                                      "launcher_pid": proc.pid,
                                      "verified_window": True,
                                      "terminate_pid_on_close": terminate_pid_on_close,
                                  })
            return f"Opening {target.name}."
        except OSError:
            return None
    if target.kind == "shell":
        try:
            os.startfile(target.value)
            ctx.registry.register("folder", target.name,
                                  window_title=target.name,
                                  extra={
                                      "shell_target": target.value,
                                      "close_policy": "unverified_ownership",
                                  })
            return f"Opening {target.name}."
        except OSError:
            return None
    if target.kind == "website":
        page = ctx.browser.open_site(target.value, name=target.name)
        if page is not None:
            return f"Opening {target.name} in the browser."
    return None


def open_owned_file_in_application(path, application, ctx, timeout=20.0):
    """Open a generated file in a verified, JARVIS-owned application window."""
    from core.application_registry import ApplicationRegistry

    target_path = Path(path).resolve()
    if not target_path.is_file():
        return False
    application_key = str(application).strip().lower()
    specifications = {
        "excel": ("microsoft excel", "excel.exe"),
        "microsoft excel": ("microsoft excel", "excel.exe"),
        "powerpoint": ("microsoft powerpoint", "powerpnt.exe"),
        "microsoft powerpoint": ("microsoft powerpoint", "powerpnt.exe"),
        "word": ("microsoft word", "winword.exe"),
        "microsoft word": ("microsoft word", "winword.exe"),
    }
    canonical_name, executable_name = specifications.get(
        application_key, (application_key, ""),
    )
    executable = ApplicationRegistry._find_executable((executable_name,)) if executable_name else None
    if not executable:
        return False
    existing_hwnds = set()
    try:
        import pygetwindow as gw
        existing_hwnds = {
            getattr(window, "_hWnd", None) for window in gw.getAllWindows()
            if getattr(window, "_hWnd", None)
        }
    except Exception:
        pass
    existing_pids = _matching_process_ids(executable)
    process = None
    try:
        if application_key in {"powerpoint", "microsoft powerpoint"}:
            # PowerPoint's supported file association opens a new document
            # window reliably; direct cold-start command lines can remain on
            # the transient "Opening" frame indefinitely.
            os.startfile(str(target_path))
        else:
            arguments = [str(executable)]
            if application_key in {"excel", "microsoft excel"}:
                arguments.append("/x")
            arguments.append(str(target_path))
            process = subprocess.Popen(
                arguments, shell=False, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, **_background_process_kwargs(),
            )
    except OSError:
        return False
    target = SimpleNamespace(value=str(executable), name=canonical_name)
    verified = _verify_launched_app(
        target, existing_hwnds, existing_pids, timeout=timeout,
    )
    if verified is None:
        return False
    pid, hwnd, window_title = verified

    def ready_window(process_id):
        from ctypes import wintypes

        windows = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM,
        )

        def visit(candidate, _parameter):
            owner = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(
                candidate, ctypes.byref(owner),
            )
            if owner.value != int(process_id or 0):
                return True
            if not ctypes.windll.user32.IsWindowVisible(candidate):
                return True
            length = ctypes.windll.user32.GetWindowTextLengthW(candidate)
            buffer = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(candidate, buffer, length + 1)
            title = buffer.value.strip()
            if title and "opening" not in title.lower():
                windows.append((int(candidate), title))
            return True

        ctypes.windll.user32.EnumWindows(callback_type(visit), 0)
        target_stem = target_path.stem.lower()
        return next(
            (item for item in windows if target_stem in item[1].lower()),
            windows[0] if windows else None,
        )

    deadline = time.time() + max(1.0, float(timeout))
    ready = None
    while time.time() < deadline:
        ready = ready_window(pid)
        if ready is not None:
            hwnd, window_title = ready
            break
        time.sleep(0.1)
    if ready is None:
        return False

    def close_window(window_handle=hwnd):
        if window_handle:
            ctypes.windll.user32.PostMessageW(int(window_handle), 0x0010, 0, 0)

    ctx.registry.register(
        "document", target_path.name, pid=pid, hwnd=hwnd,
        window_title=window_title, path=str(target_path), closer=close_window,
        extra={
            "path": str(target_path), "application": canonical_name,
            "process_name": Path(executable).name,
            "launcher_pid": process.pid if process is not None else None,
            "verified_window": True, "close_policy": "owned_only",
        },
    )
    return True


def open_thing(name, ctx, preferred_kind=None):
    """Universal opener. Returns a spoken result string."""
    name = (name or "").strip()
    if not name:
        return "Open what, exactly?"

    resolved = resolve_windows_target(name, preferred_kind=preferred_kind)
    kind_matches = (
        preferred_kind is None
        or resolved is not None and resolved.kind == preferred_kind
        or preferred_kind == "folder" and resolved is not None and resolved.kind == "shell"
    )
    if resolved is not None and kind_matches:
        launched = _launch_resolved(resolved, ctx)
        if launched:
            return launched
        return f"I found {resolved.name}, but Windows did not open it successfully."

    if preferred_kind is not None:
        noun = {"app": "application", "file": "file", "folder": "folder"}.get(
            preferred_kind, preferred_kind
        )
        return f"I couldn't find a {noun} called {name}."

    # (a) installed app — common map
    result = _launch_app(name, ctx)
    if result:
        ctx.registry.register("app", name, pid=result.get("pid"))
        return f"Opening {name}."

    # (a2) Start Menu fuzzy match
    try:
        links = _start_menu_shortcuts()
        matches = get_close_matches(name.lower(), list(links.keys()), n=1, cutoff=0.45)
        if not matches:
            matches = [k for k in links if name.lower() in k][:1]
        if matches:
            lnk = links[matches[0]]
            os.startfile(str(lnk))
            ctx.registry.register(
                "app", lnk.stem, window_title=lnk.stem,
                extra={"close_policy": "unverified_ownership"},
            )
            return f"Opening {lnk.stem}."
    except Exception:
        pass

    # (b) file by name
    try:
        found = _search_files(name)
        if found is not None:
            os.startfile(str(found))
            ctx.registry.register("app", found.name, window_title=found.stem,
                                  extra={
                                      "path": str(found),
                                      "close_policy": "unverified_ownership",
                                  })
            return f"Opening the file {found.name}."
    except Exception:
        pass

    # (c) folder path
    try:
        p = Path(name).expanduser()
        if p.exists() and p.is_dir():
            os.startfile(str(p))
            ctx.registry.register("folder", p.name, window_title=p.name,
                                  extra={
                                      "path": str(p),
                                      "close_policy": "unverified_ownership",
                                  })
            return f"Opening the folder {p.name}."
    except Exception:
        pass

    # (d) website
    if "." in name.replace(" ", "") or name.lower() in KNOWN_SITES:
        page = ctx.browser.open_site(name)
        if page is not None:
            return f"Opening {name} in the browser."

    # (e) clarify
    return (f"I couldn't find an app, file, or folder called {name}. "
            f"Did you mean an application, a file, or a website?")


def search_and_open_file(name, ctx):
    found = _search_files((name or "").strip())
    if found is None:
        return f"I couldn't find a file called {name}."
    return open_thing(str(found), ctx, preferred_kind="file")


# ---------------------------------------------------------------------------
# CLOSE
# ---------------------------------------------------------------------------
def close_thing(target, ctx):
    target = (target or "").strip()

    if target and target not in ("__all__", "__recent_folder__"):
        from skills import office_close
        if office_close.is_office_app(target):
            unsaved = office_close.has_unsaved_changes(target)
            if unsaved is True:
                ctx.speaker.speak(
                    f"{target} has unsaved changes. Say yes to save and close, "
                    "or no to keep it open."
                )
                ctx.pending = {
                    "kind": "confirm",
                    "prompt": f"close {target}",
                    "on_yes": lambda name=target: office_close.resolve_unsaved(name, "save"),
                    "on_no": lambda name=target: f"Closing {name} cancelled, sir.",
                }
                return None

    if target == "__all__":
        from skills import office_close
        for office_name in ("Word", "Excel", "PowerPoint"):
            if office_close.has_unsaved_changes(office_name) is True:
                ctx.speaker.speak(
                    f"{office_name} has unsaved changes. Close everything is paused. "
                    f"Please close or save {office_name} first."
                )
                return None
        results = ctx.registry.close_all()
        n = sum(1 for r in results if r["closed"])
        if not results:
            return "There's nothing open at the moment, sir."
        return f"Closed {n} item{'s' if n != 1 else ''} for you."

    if target == "__recent_folder__":
        entries = [entry for entry in ctx.registry.list_open()
                   if entry.get("type") == "folder"]
        if not entries:
            return "I don't have a folder open, sir."
        results = ctx.registry.close_by_name(entries[-1].get("name", ""))
        closed = any(result.get("closed") for result in results)
        return "Closed the folder, sir." if closed else "I found the folder, but couldn't close it cleanly."

    if not target:
        res = ctx.registry.close_most_recent()
        if res is None:
            return "There's nothing open at the moment, sir."
        name = res["entry"]["name"]
        return f"Closed {name}." if res["closed"] else f"I tried to close {name}, but it resisted."

    results = ctx.registry.close_by_name(target)
    if results:
        ok = sum(1 for r in results if r["closed"])
        return f"Closed {target}." if ok else f"I found {target}, but couldn't close it cleanly."

    return f"I don't have a JARVIS-owned item called {target} open."


# ---------------------------------------------------------------------------
# VOLUME (pycaw)
# ---------------------------------------------------------------------------
def _endpoint_volume():
    from comtypes import CLSCTX_ALL
    from ctypes import cast, POINTER
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def set_volume(action, level=None):
    try:
        vol = _endpoint_volume()
        if action == "mute":
            vol.SetMute(1, None)
            return "Muted."
        if action == "unmute":
            vol.SetMute(0, None)
            return "Sound back on."
        if level is not None:
            lvl = max(0.0, min(1.0, float(level) / 100.0))
            vol.SetMasterVolumeLevelScalar(lvl, None)
            return f"Volume set to {int(lvl * 100)} percent."
        current = vol.GetMasterVolumeLevelScalar()
        step = 0.1 if action == "up" else -0.1
        new = max(0.0, min(1.0, current + step))
        vol.SetMasterVolumeLevelScalar(new, None)
        return f"Volume at {int(new * 100)} percent."
    except Exception as exc:
        # fallback: media keys
        try:
            import pyautogui
            key = {"up": "volumeup", "down": "volumedown",
                   "mute": "volumemute", "unmute": "volumemute"}.get(action)
            if key:
                for _ in range(5 if action in ("up", "down") else 1):
                    pyautogui.press(key)
                return "Done."
        except Exception:
            pass
        return f"I couldn't adjust the volume ({exc})."


# ---------------------------------------------------------------------------
# SYSTEM ACTIONS
# ---------------------------------------------------------------------------
def screenshot(ctx):
    try:
        import pyautogui
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = Config.DESKTOP_PATH / f"screenshot_{ts}.png"
        img = pyautogui.screenshot()
        img.save(str(path))
        return f"Screenshot saved to your desktop as {path.name}."
    except Exception as exc:
        return f"Screenshot failed: {exc}."


def lock_pc():
    try:
        ctypes.windll.user32.LockWorkStation()
        return "Locking the workstation."
    except Exception as exc:
        return f"I couldn't lock the PC: {exc}."


def shutdown(action, ctx):
    if action == "cancel":
        os.system("shutdown /a")
        return "Shutdown cancelled."
    if getattr(ctx, "action_manager", None) is not None:
        return _do_power_action(action)
    if action in ("restart", "sleep"):
        verb = "restart" if action == "restart" else "put the computer to sleep"
        if Config.CONFIRM_SENDS:
            ctx.speaker.speak(
                f"This will {verb}. Say yes to confirm, or no to cancel."
            )
            ctx.pending = {
                "kind": "confirm",
                "prompt": action,
                "on_yes": lambda: _do_power_action(action),
                "on_no": lambda: f"{action.title()} cancelled, sir.",
            }
            return None
        return _do_power_action(action)
    if Config.CONFIRM_SENDS:
        ctx.speaker.speak(
            "This will shut down the computer in sixty seconds. "
            "Say yes to confirm, or no to cancel.")
        ctx.pending = {
            "kind": "confirm",
            "prompt": "shutdown",
            "on_yes": lambda: _do_shutdown(),
            "on_no": lambda: "Shutdown cancelled, sir.",
        }
        return None
    return _do_shutdown()


def _do_shutdown():
    os.system("shutdown /s /t 60")
    return ("Shutting down in sixty seconds. "
            "Say 'cancel shutdown' if you change your mind.")


def _do_power_action(action):
    if action == "restart":
        os.system("shutdown /r /t 15")
        return "Restarting the computer in fifteen seconds, sir."
    if action == "sleep":
        try:
            ctypes.windll.powrprof.SetSuspendState(False, True, False)
            return "Putting the computer to sleep, sir."
        except Exception as exc:
            return f"I couldn't put the computer to sleep: {exc}."
    return _do_shutdown()


def status_report():
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        system_drive = os.environ.get("SystemDrive", "C:") + "\\"
        disk = psutil.disk_usage(system_drive)
        parts = [
            f"CPU load is {cpu:.0f} percent",
            f"memory at {ram.percent:.0f} percent",
            f"drive C has {disk.free / (1024**3):.0f} gigabytes free",
        ]
        battery = psutil.sensors_battery()
        if battery is not None:
            state = "charging" if battery.power_plugged else "on battery"
            parts.append(f"battery at {battery.percent:.0f} percent, {state}")
        return "All systems report: " + ", ".join(parts) + "."
    except Exception as exc:
        return f"I couldn't compile the status report: {exc}."


# ---------------------------------------------------------------------------
# Skill dispatch entry
# ---------------------------------------------------------------------------
def _windows_controller(ctx):
    controller = getattr(ctx, "windows_controller", None)
    if controller is None:
        from core.windows_controller import WindowsController
        controller = WindowsController(ctx)
        ctx.windows_controller = controller
    return controller


def handle(intent, ctx):
    skill = intent.get("skill")
    params = intent.get("params", {}) or {}

    if skill in ("app.open", "app.open_app", "app.open_file", "app.open_folder"):
        target = params.get("target", "")
        windows = _windows_controller(ctx)
        if skill == "app.open_app":
            return windows.open_application(target)
        if skill == "app.open_file":
            return windows.open_file(target)
        if skill == "app.open_folder":
            return windows.open_folder(target)
        return open_thing(target, ctx)
    if skill == "app.search_file":
        return search_and_open_file(params.get("target", ""), ctx)
    if skill == "app.close":
        return _windows_controller(ctx).close_resource(params.get("target", ""))
    if skill == "system.volume":
        level = params.get("level")
        try:
            level = int(level) if level not in (None, "") else None
        except Exception:
            level = None
        return set_volume(params.get("action", "up"), level)
    if skill == "system.screenshot":
        return screenshot(ctx)
    if skill == "system.lock":
        return lock_pc()
    if skill == "system.shutdown":
        return shutdown(params.get("action", "shutdown"), ctx)
    if skill == "system.status":
        return status_report()
    return "I'm not sure what you want me to do with the system, sir."
