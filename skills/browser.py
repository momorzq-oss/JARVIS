"""
Browser Automation Engine — Playwright Chromium with a persistent profile
so logins (Gmail, YouTube) survive restarts. ONE shared instance serves
media, email, news and web skills via get_browser().

Every tab is registered in the Session Registry, so "close YouTube" /
"close the browser" / "close everything" all work.
"""
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import quote_plus

from config import Config


def _background_process_kwargs():
    """Prevent a console flash for non-interactive Playwright maintenance."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return {"creationflags": flags} if flags else {}


def _install_chromium():
    """Install Chromium only into JARVIS' permanent per-user browser store."""
    Config.PLAYWRIGHT_BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(Config.PLAYWRIGHT_BROWSERS_DIR)
    if not getattr(sys, "frozen", False):
        return subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            env=env,
            check=False,
            timeout=600,
            **_background_process_kwargs(),
        ).returncode == 0
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    driver_executable, driver_cli = compute_driver_executable()
    return subprocess.run(
        [str(driver_executable), str(driver_cli), "install", "chromium"],
        env={**get_driver_env(), **env},
        check=False,
        timeout=600,
        **_background_process_kwargs(),
    ).returncode == 0


# Force Playwright temp / cache dirs into JARVIS writable space so packaged
# builds never hit the PyInstaller read-only _MEIPASS temp directory.
def _set_browser_env():
    import os, tempfile
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Config.PLAYWRIGHT_BROWSERS_DIR)
    jarvis_temp = str(Config.TEMP_DIR)
    os.makedirs(jarvis_temp, exist_ok=True)
    os.environ["TMPDIR"] = jarvis_temp
    os.environ["TEMP"] = jarvis_temp
    os.environ["TMP"] = jarvis_temp
    tempfile.tempdir = jarvis_temp

try:
    _set_browser_env()
except Exception:
    pass  # harmless in test/sandbox environments

BROWSER_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


def detect_browser_executable(paths=None):
    candidates = detect_browser_executables(paths)
    return candidates[0] if candidates else None


def detect_browser_executables(paths=None):
    found = []
    for path in paths or BROWSER_PATHS:
        candidate = Path(path)
        if candidate.is_file():
            found.append(candidate)
    return found

KNOWN_SITES = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google docs": "https://docs.google.com",
    "google sheets": "https://sheets.google.com",
    "google slides": "https://slides.google.com",
    "google news": "https://news.google.com",
    "github": "https://github.com",
    "stripe": "https://dashboard.stripe.com",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com",
    "tiktok": "https://www.tiktok.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com",
    "wikipedia": "https://www.wikipedia.org",
    "chatgpt": "https://chat.openai.com",
    "openrouter": "https://openrouter.ai",
    "huggingface": "https://huggingface.co",
    "spotify": "https://open.spotify.com",
    "whatsapp web": "https://web.whatsapp.com",
    "bbc": "https://www.bbc.com/news",
    "cnn": "https://www.cnn.com",
    "outlook": "https://outlook.live.com",
    "microsoft": "https://www.microsoft.com",
    "microsoft 365": "https://www.microsoft365.com",
    "apple": "https://www.apple.com",
}


def normalize_url(target):
    """Turn 'youtube', 'youtube.com' or a full URL into a URL."""
    t = (target or "").strip()
    if not t:
        return None
    low = t.lower()
    if low in KNOWN_SITES:
        return KNOWN_SITES[low]
    if t.startswith(("http://", "https://")):
        return t
    if "." in t and " " not in t:
        return "https://" + t
    return None


class BrowserEngine:
    def __init__(self, registry):
        self.registry = registry
        self.profile_dir = str(Config.BROWSER_PROFILE_DIR)
        self._pw = None
        self._context = None
        self._lock = threading.Lock()
        self._browser_registered = False
        self._driver_process = None
        self._owned_browser_processes = {}
        _set_browser_env()  # ensure writable temp/ browser paths in packaged mode

    # ------------------------------------------------------------- lifecycle
    def ensure(self):
        """Launch the persistent browser context if not already running."""
        with self._lock:
            if self._context is not None:
                try:
                    _ = self._context.pages
                    return True
                except Exception:
                    self._context = None
            # Install Chromium if not already present (packaged builds need this)
            if not detect_browser_executables():
                try:
                    _install_chromium()
                except Exception:
                    pass
            try:
                from playwright.sync_api import sync_playwright
                self._pw = sync_playwright().start()
                self._context = self._launch()
                self._capture_owned_browser_processes()
            except Exception as exc:
                print(f"[browser] launch failed ({exc})", flush=True)
                self._teardown_pw()
                if detect_browser_executables():
                    return False
                try:
                    print("[browser] Edge and Chrome unavailable; installing Chromium permanently...",
                          flush=True)
                    _install_chromium()
                    from playwright.sync_api import sync_playwright
                    self._pw = sync_playwright().start()
                    self._context = self._launch()
                    self._capture_owned_browser_processes()
                except Exception as exc2:
                    print(f"[browser] second launch failed: {exc2}", flush=True)
                    self._teardown_pw()
                    return False
            if not self._browser_registered and self.registry is not None:
                self.registry.register(
                    "browser", "Chromium browser",
                    closer=self._close_context_only,
                )
                self._browser_registered = True
            return True

    def _launch(self):
        candidates = detect_browser_executables()
        candidates = candidates or [None]
        last_error = None
        for executable in candidates:
            kwargs = {"executable_path": str(executable)} if executable else {}
            try:
                return self._pw.chromium.launch_persistent_context(
                    self.profile_dir,
                    headless=False,
                    no_viewport=True,
                    timeout=30000,
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-session-crashed-bubble",
                        "--hide-crash-restore-bubble",
                    ],
                    ignore_default_args=["--enable-automation"],
                    **kwargs,
                )
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError("No browser executable is available")

    def _teardown_pw(self):
        # A persistent Chrome context can wait indefinitely for extensions or
        # restored tabs during context.close().  End only the process tree that
        # carries JARVIS' exact profile first; protocol cleanup is then quick and
        # cannot touch the user's normal browser profile.
        self._terminate_owned_browser_processes()
        self._terminate_driver_process()
        self._context = None
        self._pw = None

    def _capture_owned_browser_processes(self):
        """Capture browser PIDs from this engine's Playwright driver tree."""
        self._driver_process = None
        self._owned_browser_processes = {}
        try:
            import psutil
            implementation = getattr(self._pw, "_impl_obj", None)
            connection = getattr(implementation, "_connection", None)
            transport = getattr(connection, "_transport", None)
            driver = getattr(transport, "_proc", None)
            driver_pid = int(getattr(driver, "pid", 0) or 0)
            if not driver_pid:
                return
            driver_process = psutil.Process(driver_pid)
            self._driver_process = (
                driver_process.pid, driver_process.create_time()
            )
            browser_names = {
                "chrome.exe", "chromium.exe", "msedge.exe", "chrome", "chromium", "msedge",
            }
            for process in driver_process.children(recursive=True):
                try:
                    if process.name().lower() in browser_names:
                        self._owned_browser_processes[process.pid] = process.create_time()
                except Exception:
                    continue
        except Exception:
            self._driver_process = None
            self._owned_browser_processes = {}

    def _terminate_owned_browser_processes(self, timeout=2.0):
        """Terminate only the PIDs captured from this Playwright driver."""
        try:
            import psutil
            owned_by_pid = {}
            for pid, created_at in self._owned_browser_processes.items():
                try:
                    process = psutil.Process(pid)
                    if abs(process.create_time() - created_at) > 0.01:
                        continue
                    owned_by_pid[pid] = process
                    for child in process.children(recursive=True):
                        owned_by_pid[child.pid] = child
                except Exception:
                    continue
            owned = list(owned_by_pid.values())
            for process in owned:
                try:
                    process.terminate()
                except Exception:
                    pass
            _, alive = psutil.wait_procs(owned, timeout=timeout)
            for process in alive:
                try:
                    process.kill()
                except Exception:
                    pass
        except Exception:
            pass
        self._owned_browser_processes = {}

    def _terminate_driver_process(self, timeout=2.0):
        """Stop only this engine's Node driver without invoking blocking APIs."""
        captured = self._driver_process
        self._driver_process = None
        if not captured:
            return
        try:
            import psutil
            pid, created_at = captured
            process = psutil.Process(pid)
            if abs(process.create_time() - created_at) > 0.01:
                return
            descendants = process.children(recursive=True)
            process.terminate()
            _, alive = psutil.wait_procs(descendants + [process], timeout=timeout)
            for item in alive:
                try:
                    item.kill()
                except Exception:
                    pass
        except Exception:
            pass

    def _close_context_only(self):
        """Registry closer callback."""
        self._teardown_pw()
        self._browser_registered = False

    @property
    def is_running(self):
        return self._context is not None

    @property
    def context(self):
        self.ensure()
        return self._context

    # ------------------------------------------------------------------ API
    def open_site(self, target, name=None):
        """Open a site in a new tab (reusing the browser). Returns the Page."""
        url = normalize_url(target)
        if url is None:
            url = "https://www.google.com/search?q=" + str(target).replace(" ", "+")
            name = name or f"Search: {target}"
        if not self.ensure():
            return None
        try:
            page = self._context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            title = name or target
            try:
                t = page.title()
                if t:
                    title = name or t
            except Exception:
                pass
            if self.registry is not None:
                self.registry.register(
                    "browser_tab", title, page=page, window_title=title,
                    extra={"url": url},
                )
            return page
        except Exception as exc:
            print(f"[browser] open_site failed: {exc}", flush=True)
            return None

    def search_google(self, query):
        q = str(query).strip().replace(" ", "+")
        return self.open_site(
            f"https://www.google.com/search?q={q}", name=f"Google: {query}"
        )

    def search_youtube(self, query):
        query = (query or "").strip()
        if not query:
            return self.open_site("youtube")
        url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
        return self.open_site(url, name=f"YouTube: {query}")

    def close_tab(self, name):
        if self.registry is None:
            return 0
        return len(self.registry.close_by_name(name))

    def close_browser(self):
        entries = []
        if self.registry is not None:
            entries = [
                entry for entry in self.registry.list_open()
                if entry["type"] in ("browser_tab", "browser")
            ]
        self._teardown_pw()
        self._browser_registered = False
        if self.registry is not None:
            discard = getattr(self.registry, "discard_types", None)
            if callable(discard):
                discard({"browser_tab", "browser"})
        return len(entries)


# ---------------------------------------------------------------------------
# Shared singleton — media, email and news all reuse ONE browser instance.
# ---------------------------------------------------------------------------
_shared = None


def set_shared(engine):
    global _shared
    _shared = engine


def get_browser():
    return _shared
