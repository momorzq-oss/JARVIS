"""
Codex CLI / App Builder.

"Open Codex and create an app that does X":
  - if the `codex` CLI is installed, it runs in a NEW visible terminal
    inside a fresh project folder on the Desktop;
  - otherwise the cloud brain generates the code itself, writes the files,
    and opens the folder in VS Code (or Explorer).
"""
import re
import shutil
import subprocess
from pathlib import Path

from config import Config
from brain.prompts import CODER_PROMPT


def _background_process_kwargs():
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": flags} if flags else {}


def _slug(text):
    s = re.sub(r"[^\w\s-]", "", text.lower())[:40].strip()
    s = re.sub(r"[\s-]+", "_", s)
    return s or "new_app"


def _safe_relpath(p):
    p = str(p).replace("\\", "/").lstrip("/")
    if ".." in p.split("/"):
        return None
    return p


def build_app(description, ctx):
    description = (description or "").strip()
    if not description:
        return "Build an app that does what, sir?"

    folder = Config.PROJECTS_DIR / _slug(description)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return f"I couldn't create the project folder: {exc}."
    ctx.registry.register("folder", folder.name, window_title=folder.name,
                          extra={"path": str(folder)})

    codex = shutil.which("codex")
    if codex:
        prompt = (f"Build a complete working application that: {description}. "
                  f"Write all files in the current directory, then explain "
                  f"how to run it.")
        try:
            subprocess.Popen(
                [codex, prompt],
                shell=False, cwd=str(folder),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return (f"Codex is on it, sir — building in {folder.name} in a "
                    f"new terminal. Watch it work.")
        except Exception as exc:
            return f"Codex refused to start: {exc}."

    # ---- fallback: generate with the cloud brain --------------------------
    if not ctx.llm.available:
        return ("Codex isn't installed and my code brain has no OpenRouter "
                "key, sir.")
    ctx.speaker.speak("Codex isn't installed, sir — I'll write the code myself.")
    data = ctx.llm.quick_json(CODER_PROMPT.format(description=description),
                              max_tokens=6000)
    if not data or not data.get("files"):
        return "I couldn't generate that app, sir. Try a tighter description."

    written = 0
    for f in data["files"][:12]:
        rel = _safe_relpath(f.get("path", ""))
        if not rel:
            continue
        dest = folder / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(str(f.get("content", "")), encoding="utf-8")
            written += 1
        except Exception:
            continue
    if written == 0:
        return "The generation produced nothing usable, sir."

    # README with run instructions
    try:
        run_cmd = str(data.get("run_command", "")).strip()
        (folder / "README.txt").write_text(
            f"{description}\n\nRun: {run_cmd or 'see code comments'}\n",
            encoding="utf-8")
    except Exception:
        pass

    # open in VS Code if present, else Explorer
    if shutil.which("code"):
        try:
            subprocess.Popen(["code", "."], cwd=str(folder), shell=False,
                             **_background_process_kwargs())
        except Exception:
            try:
                import os
                os.startfile(str(folder))
            except Exception:
                pass
    else:
        try:
            import os
            os.startfile(str(folder))
        except Exception:
            pass

    run_note = ""
    if data.get("run_command"):
        run_note = f" Run it with: {data['run_command']}."
    return (f"Built {written} file{'s' if written != 1 else ''} in "
            f"Desktop/Projects/{folder.name}, sir, and opened the folder.{run_note}")


# ---------------------------------------------------------------------------
# Skill dispatch entry
# ---------------------------------------------------------------------------
def handle(intent, ctx):
    if intent.get("skill") == "codex.build":
        return build_app(intent.get("params", {}).get("description", ""), ctx)
    return None
