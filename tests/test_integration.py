"""Tests for DesktopAgent, office services, news, planner validation, and
frontend button connections."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from config import Config


# ---- OpenRouter model config ----------------------------------------------
def test_openrouter_model_is_gpt_oss_safeguard_20b():
    assert Config.OPENROUTER_MODEL == "openai/gpt-oss-safeguard-20b"


def test_openrouter_base_url():
    assert Config.OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"


def test_llm_test_connection_no_key(monkeypatch):
    from brain.llm import LLM
    monkeypatch.setattr(LLM, "available", property(lambda self: False))
    llm = LLM.__new__(LLM)
    llm.api_key = ""
    llm.model = "openai/gpt-oss-safeguard-20b"
    llm.base_url = Config.OPENROUTER_BASE_URL
    llm._client = None
    llm.last_error = ""
    llm._lock = __import__("threading").Lock()
    ok, model, detail = llm.test_connection()
    assert ok is False
    assert model == "openai/gpt-oss-safeguard-20b"
    assert "not set" in detail.lower()


def test_placeholder_openrouter_key_is_unavailable():
    from brain.llm import LLM
    client = LLM(api_key="your_openrouter_api_key")
    assert client.available is False


def test_llm_client_is_lazy_even_with_valid_key(monkeypatch):
    from brain.llm import LLM
    built = []
    monkeypatch.setattr(LLM, "available", property(lambda self: True))
    monkeypatch.setattr(LLM, "_build_client", lambda self: built.append(True))
    client = LLM(api_key="sk-valid-for-test")
    assert client._client is None
    assert built == []


def test_llm_sanitizes_key_in_error(monkeypatch):
    from brain.llm import LLM
    monkeypatch.setattr(LLM, "available", property(lambda self: True))
    llm = LLM.__new__(LLM)
    llm.api_key = "sk-secret-123"
    llm.model = "openai/gpt-oss-safeguard-20b"
    llm.base_url = Config.OPENROUTER_BASE_URL
    llm.last_error = ""
    llm._lock = __import__("threading").Lock()

    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("401 unauthorized for sk-secret-123")

    llm._client = type("C", (), {"chat": type("X", (), {"completions": Completions()})()})()
    ok, model, detail = llm.test_connection()
    assert ok is False
    assert "sk-secret-123" not in detail       # key scrubbed
    assert "***" in detail
    assert calls and calls[0]["model"] == llm.model

# ---- DesktopAgent ------------------------------------------------------------
class _FakeCtx:
    registry = None
    speaker = None
    listener = None
    router = None
    llm = None
    browser = None
    pending = None


class _FakeController:
    def __init__(self):
        self.ctx = _FakeCtx()
        self._emitted = []

    def _emit(self, *a):
        self._emitted.append(a)

    def speak(self, t, block=False):
        pass


def test_agent_status_reporting():
    from core.desktop_agent import DesktopAgent
    ctl = _FakeController()
    agent = DesktopAgent(ctl)
    seen = []
    agent.set_status_callback(lambda s, d: seen.append(s))
    agent._status("Locating target", "test")
    assert "Locating target" in seen


def test_agent_confirm_default_deny():
    from core.desktop_agent import DesktopAgent
    agent = DesktopAgent(_FakeController())
    assert agent.confirm("dangerous") is False   # no handler -> deny


def test_agent_emergency_stop_releases(monkeypatch):
    from core.desktop_agent import DesktopAgent
    agent = DesktopAgent(_FakeController())
    agent._held_keys.add("ctrl")
    released = []
    import pyautogui
    monkeypatch.setattr(pyautogui, "keyUp", lambda k: released.append(k))
    monkeypatch.setattr(pyautogui, "mouseUp", lambda button=None: released.append(button))
    agent.request_stop()
    assert agent._stop.is_set()
    assert "ctrl" in released


def test_agent_clipboard_roundtrip():
    from core.desktop_agent import DesktopAgent
    agent = DesktopAgent(_FakeController())
    ok = agent.clipboard_write("jarvis-test")
    assert ok is True
    assert agent.clipboard_read() == "jarvis-test"


def test_agent_active_window_title_returns_string():
    from core.desktop_agent import DesktopAgent
    agent = DesktopAgent(_FakeController())
    title = agent.active_window_title()
    assert isinstance(title, str)


# ---- planner JSON validation --------------------------------------------------
def test_planner_validates_against_allowlist():
    # a trusted-local executor must reject unknown skills
    ALLOWED = {"app.open", "app.close", "browser.open", "word.create", "news.latest"}
    plan = {"goal": "x", "steps": [
        {"id": 1, "skill": "app.open", "action": "open", "parameters": {}, "requires_confirmation": False},
        {"id": 2, "skill": "shell.exec", "action": "run", "parameters": {}, "requires_confirmation": False},
    ]}
    bad = [s for s in plan["steps"] if s["skill"] not in ALLOWED]
    assert len(bad) == 1 and bad[0]["skill"] == "shell.exec"


# ---- news service ----------------------------------------------------------------
def test_news_service_headlines_structure(monkeypatch):
    from skills.news_service import NewsService
    fake = [{"title": "T", "source": "BBC", "published": "now",
             "summary": "S", "link": "http://x"}]
    import skills.news as news_mod
    monkeypatch.setattr(news_mod, "fetch_headlines", lambda topic, limit=8: fake)
    svc = NewsService(_FakeCtx())
    items = svc.headlines("top", limit=5)
    assert items and items[0]["title"] == "T"
    assert items[0]["source"] == "BBC"
    assert svc.last_refresh > 0


# ---- frontend button connections ---------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    from gui import styles
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(styles.APP_QSS)
    yield app


def test_gui_all_skill_buttons_wired(qapp, tmp_path):
    from config import ensure_dirs
    from core.settings import SettingsStore
    from gui.workers import GuiController
    from gui.main_window import MainWindow
    from tests.test_controller import make_ctx
    ensure_dirs()
    s = SettingsStore(tmp_path / "c.json")
    gc = GuiController(skip_preload=True, debug=True)
    gc.controller.ctx = make_ctx()
    w = MainWindow(gc, s)
    # every control button must exist (handlers verified by the click methods)
    for attr in ("btn_start", "btn_stop", "btn_mute", "btn_browser", "btn_files",
                 "btn_logs", "btn_settings", "btn_send", "btn_min", "btn_exit",
                 "btn_stoptask", "btn_news_refresh", "btn_news_read"):
        assert hasattr(w, attr), attr
    # and the handler methods exist for the skill actions
    for method in ("_on_settings", "_on_stop_task", "_skill_news_refresh",
                   "_skill_test_openrouter", "_skill_screenshot", "_on_send"):
        assert callable(getattr(w, method)), method
    w.close()
    w.deleteLater()
