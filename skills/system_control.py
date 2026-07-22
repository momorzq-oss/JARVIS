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
import subprocess
import time
from difflib import get_close_matches, SequenceMatcher
from pathlib import Path

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


def _launch_resolved(target, ctx):
    if target.kind in ("folder", "file"):
        path = Path(target.value)
        if not path.exists():
            return None
        try:
            if target.kind == "folder":
                existing_hwnds = set()
                try:
                    import pygetwindow as gw
                    existing_hwnds = {
                        getattr(window, "_hWnd", None) for window in gw.getAllWindows()
                        if getattr(window, "_hWnd", None)
                    }
                except Exception:
                    pass
                proc = subprocess.Popen(["explorer.exe", str(path)], shell=False)
                time.sleep(0.2)
                if proc.poll() not in (None, 0):
                    return None
                pid = None
                hwnd = None
                window_title = path.name or str(path)
                try:
                    import pygetwindow as gw
                    deadline = time.time() + 3.0
                    matches = []
                    while time.time() < deadline and not matches:
                        matches = [window for window in gw.getAllWindows()
                                   if window.title and path.name.lower() in window.title.lower()
                                   and getattr(window, "_hWnd", None) not in existing_hwnds]
                        if not matches:
                            time.sleep(0.1)
                    if matches:
                        hwnd = getattr(matches[-1], "_hWnd", None)
                        window_title = matches[-1].title
                        if hwnd:
                            process_id = ctypes.c_ulong()
                            ctypes.windll.user32.GetWindowThreadProcessId(
                                int(hwnd), ctypes.byref(process_id)
                            )
                            pid = int(process_id.value) or None
                except Exception:
                    pass
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
            proc = subprocess.Popen([target.value], shell=False,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    **_background_process_kwargs())
            time.sleep(0.25)
            if proc.poll() not in (None, 0):
                return None
            pid = proc.pid if proc.poll() is None else None
            hwnd = None
            window_title = target.name
            try:
                import pygetwindow as gw
                deadline = time.time() + 3.0
                matches = []
                target_low = target.name.lower()
                while time.time() < deadline and not matches:
                    matches = [
                        window for window in gw.getAllWindows()
                        if window.title and target_low in window.title.lower()
                        and getattr(window, "_hWnd", None) not in existing_hwnds
                    ]
                    if not matches:
                        time.sleep(0.1)
                if matches:
                    hwnd = getattr(matches[-1], "_hWnd", None)
                    window_title = matches[-1].title
                    if hwnd:
                        process_id = ctypes.c_ulong()
                        ctypes.windll.user32.GetWindowThreadProcessId(
                            int(hwnd), ctypes.byref(process_id)
                        )
                        pid = int(process_id.value) or pid
            except Exception:
                pass
            ctx.registry.register("app", target.name, pid=pid, hwnd=hwnd,
                                  window_title=window_title,
                                  exe_path=target.value,
                                  extra={"process_name": Path(target.value).name})
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
