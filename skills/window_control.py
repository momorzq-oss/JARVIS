"""
Window control - bring-to-front, minimize, maximize, restore, focus, close.

Resolves a window via the Session Registry first (exact name / exe name /
window title / friendly name / fuzzy), then falls back to scanning live
windows with pygetwindow. Actions are conservative: never terminate an
unrelated process with a similar name.
"""
from difflib import get_close_matches


def _show_owned_window(entry, verb):
    """Use non-blocking Win32 state changes for a verified registry HWND."""
    hwnd = int((entry or {}).get("hwnd") or (entry or {}).get("window_handle") or 0)
    if not hwnd:
        return False
    try:
        import ctypes
        if not ctypes.windll.user32.IsWindow(hwnd):
            return False
        commands = {"minimize": 6, "maximize": 3, "restore": 9, "focus": 9}
        command = commands.get(verb)
        if command is None:
            return False
        ctypes.windll.user32.ShowWindowAsync(hwnd, command)
        if verb == "focus":
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _live_windows():
    try:
        import pygetwindow as gw
        return [w for w in gw.getAllWindows() if w.title]
    except Exception:
        return []


def _match_windows(target):
    """Return live windows matching target by title (substring then fuzzy)."""
    target_l = (target or "").strip().lower()
    if not target_l:
        return []
    wins = _live_windows()
    hits = [w for w in wins if target_l in w.title.lower()]
    if hits:
        return hits
    titles = {w.title: w for w in wins}
    close = get_close_matches(target_l, [t.lower() for t in titles], n=1, cutoff=0.4)
    for lowered in close:
        for original, win in titles.items():
            if original.lower() == lowered:
                return [win]
    return []


def _registry_entry(target, ctx):
    reg = getattr(ctx, "registry", None)
    if reg is None or not target:
        return None
    hits = reg.find_by_name(target)
    return hits[0] if hits else None


def _resolve(target, ctx):
    """Return (entry, window). Either may be None."""
    entry = _registry_entry(target, ctx)
    win = None
    if entry and entry.get("window_title"):
        matched = _match_windows(entry["window_title"])
        win = matched[0] if matched else None
    if win is None:
        matched = _match_windows(target)
        win = matched[0] if matched else None
    return entry, win


def _act(target, ctx, verb, methods, spoken):
    target = (target or "").strip()
    if not target:
        return f"What should I {verb}, sir?"
    entry = _registry_entry(target, ctx)
    if _show_owned_window(entry, verb):
        if entry is not None and verb in ("minimize", "maximize", "restore"):
            try:
                state = "open" if verb == "restore" else f"{verb}d"
                ctx.registry.set_state(entry["id"], state)
            except Exception:
                pass
        return spoken.format(name=target)
    entry, win = _resolve(target, ctx)
    if win is None:
        return f"I couldn't find a window for {target}, sir."
    try:
        for method in methods:
            try:
                getattr(win, method)()
            except Exception:
                continue
        if entry is not None and verb in ("minimize", "maximize", "restore"):
            try:
                state = "open" if verb == "restore" else f"{verb}d"
                ctx.registry.set_state(entry["id"], state)
            except Exception:
                pass
        return spoken.format(name=target)
    except Exception as exc:
        return f"I couldn't {verb} {target}: {exc}."


def bring_to_front(target, ctx):
    target = (target or "").strip()
    if not target:
        return "Bring what to the front, sir?"
    entry = _registry_entry(target, ctx)
    if _show_owned_window(entry, "focus"):
        return f"Bringing {target} to the front, sir."
    entry, win = _resolve(target, ctx)
    if win is None:
        return f"I couldn't find a window for {target}, sir."
    try:
        try:
            win.restore()
        except Exception:
            pass
        win.activate()
        return f"Bringing {target} to the front, sir."
    except Exception as exc:
        return f"I couldn't focus {target}: {exc}."


def minimize_window(target, ctx):
    return _act(target, ctx, "minimize", ["minimize"], "Minimizing {name}, sir.")


def maximize_window(target, ctx):
    return _act(target, ctx, "maximize", ["maximize"], "Maximizing {name}, sir.")


def restore_window(target, ctx):
    return _act(target, ctx, "restore", ["restore"], "Restoring {name}, sir.")


def focus_window(target, ctx):
    return bring_to_front(target, ctx)


def handle(intent, ctx):
    skill = intent.get("skill")
    params = intent.get("params", {}) or {}
    target = params.get("target", "")
    if skill in ("window.front", "window.focus"):
        return bring_to_front(target, ctx)
    if skill == "window.minimize":
        return minimize_window(target, ctx)
    if skill == "window.maximize":
        return maximize_window(target, ctx)
    if skill == "window.restore":
        return restore_window(target, ctx)
    if skill == "window.close":
        from skills.system_control import close_thing
        return close_thing(target, ctx)
    return "I'm not sure which window action you want, sir."
