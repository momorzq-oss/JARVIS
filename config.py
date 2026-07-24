"""
JARVIS configuration — loads .env, defines all paths, secrets and constants.
Everything else in the project imports from here.
"""
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):
        return False

# --------------------------------------------------------------------------
# Base directories
# --------------------------------------------------------------------------
SOURCE_DIR = Path(__file__).resolve().parent
BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SOURCE_DIR
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", SOURCE_DIR))
LOCAL_APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
USER_DATA_DIR = LOCAL_APP_DATA / "JARVIS"
DATA_DIR = USER_DATA_DIR / "data" if getattr(sys, "frozen", False) else BASE_DIR / "data"
RUNTIME_DIR = USER_DATA_DIR / "runtime"
TEMP_DIR = USER_DATA_DIR / "temp" if getattr(sys, "frozen", False) else SOURCE_DIR / ".test_tmp"

def activate_external_runtime() -> bool:
    """Enable the optional frozen runtime only after bundled imports fail."""
    if not getattr(sys, "frozen", False) or not RUNTIME_DIR.is_dir():
        return False
    runtime_path = str(RUNTIME_DIR)
    if runtime_path not in sys.path:
        sys.path.insert(0, runtime_path)
    for dll_dir in (RUNTIME_DIR, RUNTIME_DIR / "torch" / "lib"):
        if dll_dir.is_dir() and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(dll_dir))
            except OSError:
                pass
    return True

# Load .env: try alongside the exe first, then bundled resource, then CWD
_env_loaded = False
for _candidate in (BASE_DIR / ".env", RESOURCE_DIR / ".env", SOURCE_DIR / ".env"):
    if _candidate.exists():
        load_dotenv(_candidate)
        _env_loaded = True
        break
if not _env_loaded:
    load_dotenv(BASE_DIR / ".env")  # fallback attempt


def _default_desktop() -> Path:
    """Locate the real Desktop folder (handles OneDrive-redirected desktops)."""
    home = Path.home()
    for candidate in (home / "OneDrive" / "Desktop", home / "Desktop"):
        if candidate.exists():
            return candidate
    return home / "Desktop"


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip().strip('"').strip("'")
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def valid_openrouter_key(value: str) -> bool:
    value = str(value or "").strip()
    if not value.startswith("sk-or-v1-"):
        return False
    lowered = value.lower()
    return not any(marker in lowered for marker in (
        "your_", "your-", "replace", "placeholder", "changeme", "example",
    ))


class Config:
    # ---- Paths -------------------------------------------------------------
    SOURCE_DIR = SOURCE_DIR
    BASE_DIR = BASE_DIR
    DATA_DIR = DATA_DIR
    USER_DATA_DIR = USER_DATA_DIR
    RUNTIME_DIR = RUNTIME_DIR
    TEMP_DIR = TEMP_DIR
    DESKTOP_PATH = _env_path("DESKTOP_PATH", _default_desktop())
    DOCUMENTS_PATH = _env_path("DOCUMENTS_PATH", Path.home() / "Documents")
    DOWNLOADS_PATH = _env_path("DOWNLOADS_PATH", Path.home() / "Downloads")
    BROWSER_PROFILE_DIR = _env_path("BROWSER_PROFILE_DIR", USER_DATA_DIR / "browser-profile")
    PLAYWRIGHT_BROWSERS_DIR = _env_path("PLAYWRIGHT_BROWSERS_DIR", USER_DATA_DIR / "browsers")
    LOG_DIR = _env_path("LOG_DIR", USER_DATA_DIR / "logs")
    CACHE_DIR = _env_path("CACHE_DIR", DATA_DIR / "cache")
    PROJECTS_DIR = DESKTOP_PATH / "Projects"

    # ---- Cloud brain (OpenRouter, OpenAI-compatible) ------------------------
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
    OPENROUTER_MODEL = os.getenv(
        "OPENROUTER_MODEL", "openai/gpt-oss-safeguard-20b"
    ).strip()
    OPENROUTER_BASE_URL = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    ).strip()

    # ---- Local router brain -------------------------------------------------
    ROUTER_MODEL_NAME = os.getenv(
        "ROUTER_MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct"
    ).strip()

    # ---- Email (SMTP / IMAP fallback — browser Gmail mode needs neither) ----
    EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", os.getenv("GMAIL_ADDRESS", "")).strip()
    EMAIL_APP_PASSWORD = os.getenv(
        "EMAIL_APP_PASSWORD", os.getenv("GMAIL_APP_PASSWORD", "")
    ).strip()

    # ---- News ---------------------------------------------------------------
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "").strip()  # optional; RSS needs no key

    # ---- Voice --------------------------------------------------------------
    WAKE_WORD = os.getenv("WAKE_WORD", "hey_jarvis").strip()
    TTS_VOICE = os.getenv(
        "TTS_VOICE", os.getenv("BRITISH_VOICE", "en-GB-RyanNeural")
    ).strip()
    PIPER_MODEL = _env_path(
        "PIPER_MODEL",
        RESOURCE_DIR / "data" / "piper" / "en_GB-alan-medium.onnx",
    )
    VOICE_SPEED = float(os.getenv("VOICE_SPEED", "1.0"))
    VOICE_PITCH = int(os.getenv("VOICE_PITCH", "0"))
    WHISPER_MODEL = os.getenv(
        "WHISPER_MODEL", os.getenv("WHISPER_MODEL_SIZE", "base")
    ).strip()
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto").strip().lower()
    GPU_ENABLED = _env_flag("GPU_ENABLED", True)
    # The local Qwen model is both the intent classifier and the offline
    # conversational fallback.  Packaged builds now include its runtime, so
    # keep it enabled unless the user explicitly opts out.
    LOCAL_ROUTER_ENABLED = _env_flag("LOCAL_ROUTER_ENABLED", True)
    OPENROUTER_TIMEOUT = int(os.getenv("OPENROUTER_TIMEOUT", "60"))
    OPENROUTER_RETRIES = int(os.getenv("OPENROUTER_RETRIES", "3"))

    # ---- Optional Colibri local runtime -----------------------------------
    # JARVIS never installs, starts, or exposes Colibri automatically.  When
    # enabled it may only contact its documented loopback OpenAI-compatible API.
    COLIBRI_ENABLED = _env_flag("COLIBRI_ENABLED", False)
    COLIBRI_MODE = os.getenv("COLIBRI_MODE", "disabled").strip().lower()
    COLIBRI_REPOSITORY_URL = os.getenv(
        "COLIBRI_REPOSITORY_URL", "https://github.com/JustVugg/colibri.git"
    ).strip()
    COLIBRI_COMMIT = os.getenv(
        "COLIBRI_COMMIT", "44e489b196c9b7876b3d37a0570ebf1c6f90f54c"
    ).strip()
    COLIBRI_BASE_URL = os.getenv("COLIBRI_BASE_URL", "http://127.0.0.1:8000/v1").strip()
    COLIBRI_MODEL = os.getenv("COLIBRI_MODEL", "glm-5.2-colibri").strip()
    COLIBRI_TIMEOUT_SECONDS = int(os.getenv("COLIBRI_TIMEOUT_SECONDS", "60"))

    # ---- Optional Hermes orchestration ------------------------------------
    # Disabled unless a separately installed Hermes instance passes JARVIS's
    # protocol and safety checks. Hermes never receives desktop primitives.
    HERMES_ENABLED = _env_flag("HERMES_ENABLED", False)
    HERMES_MODE = os.getenv("HERMES_MODE", "disabled").strip().lower()
    HERMES_EXECUTABLE = os.getenv("HERMES_EXECUTABLE", "").strip()
    HERMES_BASE_URL = os.getenv("HERMES_BASE_URL", "").strip()
    HERMES_MODEL = os.getenv("HERMES_MODEL", "").strip()
    HERMES_PROVIDER = os.getenv("HERMES_PROVIDER", "openrouter").strip()
    HERMES_TIMEOUT_SECONDS = int(os.getenv("HERMES_TIMEOUT_SECONDS", "120"))
    HERMES_MAX_STEPS = int(os.getenv("HERMES_MAX_STEPS", "25"))
    HERMES_MAX_RETRIES = int(os.getenv("HERMES_MAX_RETRIES", "2"))
    HERMES_MAX_CONCURRENT_TASKS = int(os.getenv("HERMES_MAX_CONCURRENT_TASKS", "2"))
    HERMES_BACKGROUND_TASKS_ENABLED = _env_flag("HERMES_BACKGROUND_TASKS_ENABLED", False)
    HERMES_SCHEDULING_ENABLED = _env_flag("HERMES_SCHEDULING_ENABLED", False)
    HERMES_LEARNING_ENABLED = _env_flag("HERMES_LEARNING_ENABLED", False)
    HERMES_TOOL_ACCESS_MODE = os.getenv("HERMES_TOOL_ACCESS_MODE", "jarvis_registry_only").strip()
    LIVE_TYPING_MODE = os.getenv("LIVE_TYPING_MODE", "section").strip().lower()
    LIVE_TYPING_DELAY_MS = int(os.getenv("LIVE_TYPING_DELAY_MS", "20"))

    # ---- Behaviour flags ------------------------------------------------------
    AUTO_SEND = _env_flag("AUTO_SEND", False)          # skip per-message confirmations
    CONFIRM_SENDS = _env_flag("CONFIRM_SENDS", True)   # master switch for send/shutdown confirmations
    MUSIC_SITE = os.getenv("MUSIC_SITE", "youtube").strip().lower()
    MUSIC_SEARCH_SUFFIX = os.getenv("MUSIC_SEARCH_SUFFIX", "official audio").strip()
    OWNER_ADDRESS = os.getenv("OWNER_NAME", "sir").strip()  # how JARVIS addresses you

    # ---- Security and Permissions -------------------------------------------
    PERMISSION_SCOPES = {
        "SAFE_READ",
        "SAFE_WRITE",
        "DESKTOP_CONTROL",
        "FILE_MODIFY",
        "FILE_DELETE",
        "BROWSER_NAVIGATE",
        "FORM_SUBMIT",
        "EMAIL_DRAFT",
        "EMAIL_SEND",
        "OFFICE_EDIT",
        "SYSTEM_POWER",
        "ADMINISTRATOR",
        "SECURITY_CHANGE",
    }

    CONFIRMATION_RULES = {
        "no_confirmation": {
            "open_application", "open_folder", "read_file", "read_page",
            "read_news", "create_temporary_test_data",
        },
        "confirmation_required": {
            "move_or_rename_personal_files", "delete_files", "send_email",
            "submit_forms", "close_unsaved_documents", "organize_desktop",
            "control_system_power", "run_elevated_command",
            "change_security_settings", "close_everything",
        },
    }

    # ---- Audit Log ----------------------------------------------------------
    AUDIT_LOG_FILE = Path(os.getenv("AUDIT_LOG_FILE", DATA_DIR / "audit_log.json"))
    DESKTOP_ACTION_LOG_FILE = LOG_DIR / "desktop_actions.jsonl"
    WEB_ACTION_LOG_FILE = LOG_DIR / "web_actions.jsonl"
    CREATED_FILES_DIR = DOCUMENTS_PATH / "Jarvis Created Files"

    # ---- Persistent data files ------------------------------------------------
    MEMORY_FILE = _env_path("MEMORY_FILE", DATA_DIR / "memory.json")
    REGISTRY_FILE = DATA_DIR / "session_registry.json"
    ORGANIZER_LOG = DATA_DIR / "organizer_log.json"
    RESEARCH_SESSION_FILE = DATA_DIR / "research_session.json"
    NEWS_CACHE_FILE = DATA_DIR / "news_cache.json"

    # ---- Tuning ----------------------------------------------------------------
    ROUTER_MAX_NEW_TOKENS = int(os.getenv("ROUTER_MAX_NEW_TOKENS", "140"))
    NEWS_CACHE_MINUTES = int(os.getenv("NEWS_CACHE_MINUTES", "15"))
    CHAT_HISTORY_TURNS = int(os.getenv("CHAT_HISTORY_TURNS", "20"))
    LISTEN_MAX_SECONDS = float(os.getenv("LISTEN_MAX_SECONDS", "20"))
    WAKE_THRESHOLD = float(os.getenv("WAKE_THRESHOLD", "0.5"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()


def ensure_dirs() -> None:
    for p in (
        Config.DATA_DIR,
        Config.BROWSER_PROFILE_DIR,
        Config.PLAYWRIGHT_BROWSERS_DIR,
        Config.LOG_DIR,
        Config.CACHE_DIR,
        Config.TEMP_DIR,
        Config.PROJECTS_DIR,
        Config.CREATED_FILES_DIR,
    ):
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def require_openrouter() -> bool:
    return valid_openrouter_key(Config.OPENROUTER_API_KEY)
