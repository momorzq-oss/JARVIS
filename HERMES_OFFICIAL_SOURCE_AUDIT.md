# Hermes Official Source Audit

- Repository: `https://github.com/NousResearch/hermes-agent`
- Audited commit: `32a9f2acbcc5c0da9e8e90ccd4c2c1189e5e5da6` (`main`, 2026-07-22)
- License: MIT
- Official Windows installer: `https://hermes-agent.nousresearch.com/install.ps1`
- Downloaded-installer SHA-256: `B5BDF0E959677DE0168F8CFB5F9175C7B57ADF5C4319A1C2FC9BEC1F46FBDB6E`

## Official installation layout

The official native-Windows installer uses `%LOCALAPPDATA%\\hermes` by default, provisions Python 3.11 (with 3.12/3.13/3.10 fallbacks), uv, Node 22, ripgrep, ffmpeg, and a portable Git Bash/MinGit. It creates an independently managed Hermes environment and does not target the JARVIS project directory or JARVIS Python environment.

The documented commands are `hermes`, `hermes model`, `hermes tools`, `hermes config`, `hermes gateway`, `hermes setup`, `hermes update`, and `hermes doctor`. The project documents persistent memory, scheduled automation, a messaging gateway, skill learning, and local/Docker/SSH terminal backends.

## Security finding and installation decision

The official installer and documentation explicitly describe shell commands, autonomous skills, schedules, messaging gateways, and external tools. JARVIS therefore does not expose the full Hermes tool surface during the pilot.

After the user approved a staged external install, the reviewed repository and its independent Python environment were installed as the current user under `%LOCALAPPDATA%\hermes`, at the audited commit above. The optional Node/browser, messaging-SDK, setup, configuration, and gateway stages were not run. The JARVIS project, Python 3.12 environment, Piper, Whisper, OpenWakeWord, and verified executable were not replaced. The runtime remains disabled in JARVIS by default.

The reviewed machine-readable integration path is the official one-shot `hermes chat --quiet --query` CLI. JARVIS adds `--safe-mode`, one maximum turn, and the official empty `context_engine` toolset, then validates the complete stdout document as protocol 1.0 JSON. The adapter uses `shell=False`, exposes no Hermes-native execution tool, and now owns and cancels its exact subprocess and descendants during stop, shutdown, timeout, or emergency stop.

## Network and data handling

Hermes supports OpenRouter and other providers, so plan prompts leave the device when a live provider request is explicitly made. Its messaging gateway can connect to external platforms and optional tools can use network services; none are enabled through JARVIS. Secrets remain in provider-supported external configuration and are not copied into source, logs, or reports. The attempted pilot was rate-limited before producing a model response.

## Sources

- https://github.com/NousResearch/hermes-agent
- https://github.com/NousResearch/hermes-agent/blob/main/README.md
- https://hermes-agent.nousresearch.com/install.ps1
