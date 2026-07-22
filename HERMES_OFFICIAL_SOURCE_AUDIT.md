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

**Installation has not passed JARVIS's pilot safety gate.** The official installer and documentation explicitly provision Git Bash and describe Hermes executing shell commands, autonomous skills, scheduling, messaging gateways, and external tools. Those defaults conflict with the requested boundary that Hermes must not have unrestricted shell, file, browser, Office, mouse, keyboard, or Windows control.

No installer was executed. No Hermes binary, dependencies, gateway, tools, provider keys, memory, schedules, or messaging integrations were installed. JARVIS therefore uses a disabled-by-default adapter and only accepts its own structured plan format. A future installation requires a reviewed JARVIS-only toolset/isolated terminal policy plus a real structured-planning interface; neither is claimed by this audit.

## Network and data handling

Hermes supports OpenRouter and other providers, so prompts may leave the device according to provider configuration. Its messaging gateway can connect to external platforms and its optional tools can use network services. JARVIS will not populate Hermes credentials, enable gateway endpoints, expose API keys, or enable schedules/learning.

## Sources

- https://github.com/NousResearch/hermes-agent
- https://github.com/NousResearch/hermes-agent/blob/main/README.md
- https://hermes-agent.nousresearch.com/install.ps1
