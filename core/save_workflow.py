"""Safe multi-turn save-location resolution for generated documents."""
import re
from dataclasses import dataclass, field
from pathlib import Path

from config import Config
from skills.windows_targets import known_folders


@dataclass
class PendingSaveRequest:
    task_id: str
    document_type: str
    suggested_filename: str
    suggested_extension: str
    current_application: str
    available_locations: tuple[str, ...] = (
        "Desktop", "Downloads", "Documents", "OneDrive"
    )
    requested_location: str = ""
    resolved_path: str = ""
    overwrite_required: bool = False
    directory_creation_required: bool = False
    stage: str = "location"
    save_callback: object = field(default=None, repr=False)

    def resolve(self, response):
        raw = (response or "").strip().strip('"').strip("'")
        raw = re.sub(r"^(?:save (?:it )?(?:in|to)|in|to)\s+", "", raw, flags=re.I)
        folders = known_folders()
        low = raw.lower().strip(" .")

        base = None
        child = ""
        for key in ("desktop", "downloads", "documents", "onedrive"):
            if low == key or low.startswith(key + " "):
                base = folders.get(key)
                child_match = re.search(r"(?:under|in|inside)\s+(.+)$", raw, re.I)
                child = child_match.group(1).strip(" .") if child_match else ""
                break

        if base is None:
            named = re.sub(r"^(?:the )?", "", low)
            named = re.sub(r"\s+folder$", "", named).strip()
            if named in {
                "jarvis .test_tmp", "jarvis test", "jarvis test folder",
                ".test_tmp", "test_tmp",
            }:
                base = Config.TEMP_DIR

        if base is None:
            candidate = Path(raw).expanduser()
            if candidate.is_absolute():
                if candidate.suffix:
                    final = candidate
                else:
                    base = candidate
            else:
                return None

        if base is not None:
            base = Path(base)
            if child:
                base = base / child
            filename = _safe_filename(self.suggested_filename)
            extension = self.suggested_extension
            if extension and not filename.lower().endswith(extension.lower()):
                filename += extension
            final = base / filename

        self.requested_location = response
        self.resolved_path = str(final)
        self.overwrite_required = final.exists()
        self.directory_creation_required = not final.parent.exists()
        self.stage = "confirm"
        return final

    def save(self):
        if not self.resolved_path or self.save_callback is None:
            return False
        path = Path(self.resolved_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.save_callback(str(path))
        return path.exists()


def _safe_filename(value):
    cleaned = re.sub(r'[<>:"/\\|?*]', "", (value or "document")).strip()
    return cleaned or "document"
