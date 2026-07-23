# JARVIS Capability Registry Report

Date: 2026-07-23

## Result

- Registry: `core/capability_registry.py`.
- Health engine: `core/capability_health.py`.
- GUI page: `gui/capabilities_page.py`.
- Capabilities discovered: 209.
- Working: 199.
- Requires login: 10.
- Missing: 0.
- Broken: 0.
- Unassigned permissions: 0.
- Health scan error: none.

The live Settings verification confirms WhatsApp Desktop is signed in, so its registered operations now report `WORKING`. The ten login-required records are all Gmail/email operations tied to the same uncompleted Google sign-in: `emailer.handle`, `emailer.check_email`, `emailer.compose_email`, `emailer.read_email`, `emailer.reply_last`, `email.check`, `email.read`, `email.compose`, `email.reply`, and `email.send`. Settings provides the real **Open Google sign-in** and **Verify Gmail** controls; JARVIS cannot complete or claim that user-authenticated login itself.

The three additional working records are the constrained Hermes research pilot adapters: `research.search_web`, `research.read_source`, and `research.summarize_sources`. They call existing JARVIS research services, do not grant Hermes-native tools, and reject private-network source reads.

## Commands

`/help`, `/skills`, `/status`, `/capabilities`, and `/selftest` all returned registry-backed responses in source typed mode.

`/skills` and `/capabilities` are generated only from discovered registry records, not directly from the tool allowlist.

## Health Semantics

The registry reports WORKING, CONNECTED, DISABLED, REQUIRES_CONFIGURATION, REQUIRES_LOGIN, BROKEN, MISSING, or DEGRADED. Import and health-check failures degrade individual records rather than preventing startup.

System metrics returned WORKING. RAM, disk, and Python thread count are collected through bounded local calls. CPU, network, GPU, VRAM, and temperature remain `Unavailable` rather than being invented or risking a blocking performance-counter query.

## Hermes

Hermes Agent v0.19.0 is installed externally and is visible through real GUI health status, but remains disabled in JARVIS until a provider response passes the strict structured-plan protocol and the required pilots pass. The adapter, protocol, cancellation, task-manager, capability-boundary, and GUI-health regressions are implemented; packaged dependency validation remains gated.
