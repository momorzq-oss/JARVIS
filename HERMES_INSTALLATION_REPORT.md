# Hermes Installation Report

Status: **installed externally, pilot disabled**.

## Installer record

- Source URL: `https://hermes-agent.nousresearch.com/install.ps1`
- Local inspected file: `%TEMP%\\jarvis-hermes-install.ps1`
- SHA-256: `B5BDF0E959677DE0168F8CFB5F9175C7B57ADF5C4319A1C2FC9BEC1F46FBDB6E`
- Installed repository HEAD: `32a9f2acbcc5c0da9e8e90ccd4c2c1189e5e5da6`
- Runtime-reported upstream release commit: `7c9d0526` (the runtime reports local `32a9f2ac`, `+9722 carried commits`)
- Installation was run as the current user, never elevated.

The official installer was downloaded, hashed, and reviewed. The repository stage and independently managed Python environment were installed under `%LOCALAPPDATA%\\hermes`, outside JARVIS, using commit `32a9f2acbcc5c0da9e8e90ccd4c2c1189e5e5da6`. Optional Node/browser and messaging-SDK stages were not run by this staged install.

- Version: Hermes Agent v0.19.0 (2026.7.20); Python 3.11.15.
- Executable launcher: `%LOCALAPPDATA%\\hermes\\hermes-agent\\hermes` using its `venv\\Scripts\\python.exe`.
- Data/config: `%LOCALAPPDATA%\\hermes` (existing user provider settings were not read or modified).
- Gateway: not started; no Hermes/uvicorn/node process remains running.
- `hermes --help` and `hermes doctor`: run successfully. Doctor reported no active security advisories, an outdated configuration schema (v31 versus v33), four high-severity build-tool findings across the optional web/ui-tui workspaces, optional provider keys/logins not configured, and optional messaging SDKs absent. Global Hermes tool availability exists and is never exposed through JARVIS.
- API keys: not read, copied, or logged.

A zero-tool OpenRouter request reached the configured model and returned text with no tool calls, but its JSON mixed request metadata into the response and omitted required step safety fields. Strict protocol validation rejected it. The adapter prompt now includes the exact five-key response and eleven-key step contracts; four later bounded retries were rate-limited by upstream provider Groq (HTTP 429). No plan or action was accepted or executed. The constrained adapter remains disabled, reports provider failures without secrets, and is cancellable through normal stop, shutdown, timeout, and emergency-stop paths. GUI health now probes off the presentation thread and displays the real external v0.19.0 version, commits, install path, Python, and SDK details. Legacy `openai/gpt-oss-120b` settings migrate persistently to `openai/gpt-oss-safeguard-20b`. The complete suite reports 635 collected and 635 passed.

The JARVIS Settings window now applies the supported `cli`/`disabled` mode, provider, model, and concurrency values to the live adapter. Its explicit **Open Official Provider / Model Setup** button launches the audited external `hermes model` picker directly with `shell=False`; JARVIS never reads or stores the credentials entered through that official flow. Background work, schedules, and learning remain visibly locked off.

## Installer behavior observed

- Repository modified: `%LOCALAPPDATA%\\hermes\\hermes-agent` only.
- Runtime created: `%LOCALAPPDATA%\\hermes\\hermes-agent\\venv` with Python 3.11.15.
- Managed dependency utility: `%LOCALAPPDATA%\\hermes\\bin\\uv.exe`.
- Existing per-user PATH entries are `%LOCALAPPDATA%\\hermes\\hermes-agent\\venv\\Scripts` and `%LOCALAPPDATA%\\hermes\\bin`; no JARVIS PATH or Python environment was changed.
- The reviewed full installer can provision Git/Node/ripgrep/ffmpeg, write templates, and install platform SDKs. This staged run used only repository, venv, and Python-dependency stages; it did not run optional Node/browser, messaging-SDK, setup, configure, or gateway stages.
- No Hermes gateway, dashboard, `serve`, proxy, cron, webhook, or messaging process was started. The official dashboard default is port 9119, but it was not bound.
- Hermes includes Git Bash support for its own terminal tooling. JARVIS never invokes that tooling; its adapter only uses the external Python launcher with `shell=False`.
- Removal is through the official `hermes uninstall` command or deletion of `%LOCALAPPDATA%\\hermes` after stopping Hermes processes. Neither action was performed.
