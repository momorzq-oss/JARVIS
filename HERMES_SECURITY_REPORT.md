# Hermes Security Report

- Default state: `HERMES_ENABLED=false`, `HERMES_MODE=disabled`.
- No Hermes process, gateway, HTTP endpoint, model provider, schedule, memory, learned skill, or external messaging platform is started.
- The adapter permits only `hermes --help` and `hermes doctor` diagnostics when explicitly enabled in `cli` mode. It uses argument lists with `shell=False`.
- JARVIS accepts only pilot capability identifiers, never raw commands, executable paths, code, shell text, or input coordinates.
- `stop_task()` cancels all Hermes task records in addition to existing automation/live-task stop paths.
- Piper remains the sole production speech service; no ElevenLabs dependency or configuration was introduced.

Remaining requirement: an official, reviewable structured planning interface that can be isolated from all Hermes tools. Until then, live Hermes planning remains blocked.
