# Colibri Integration Audit

Audited repository: `https://github.com/JustVugg/colibri.git`
Pinned main commit: `44e489b196c9b7876b3d37a0570ebf1c6f90f54c`
Audit date: 2026-07-22

## Verdict

Approved only as an **optional, externally managed local text-model service**. It is not installed, cloned, built, started, or packaged by JARVIS. The adapter is disabled by default and only accepts a documented loopback HTTP endpoint.

## What it is

Colibri is an Apache-2.0 C runtime for the GLM-5.2 744B MoE model, backed by a Python launcher/gateway. It streams experts from disk; the recommended int4 model needs roughly 370–384 GB of local NVMe storage. It does not replace Piper, Whisper, or OpenWakeWord and has no microphone/audio role.

## Platform and dependencies

- Windows 11: supported; native CPU build needs MinGW-w64 `gcc` and `make`.
- Optional GPU tier needs CUDA Toolkit and MSVC Build Tools.
- Runtime engine: C with no Python dependency; the converter and OpenAI-compatible gateway use Python 3.
- Model download: manual, resumable Hugging Face download; it is intentionally not automated here.
- Native binaries: `glm.exe`, optionally `coli_cuda.dll`; neither is bundled or launched by JARVIS.

## Interfaces and security review

- Official interface selected: `coli serve`, a text-only OpenAI-compatible API (`/v1/models`, `/v1/chat/completions`, `/health`).
- Default binding is localhost. The JARVIS adapter allows only `127.0.0.1`, `localhost`, or `::1` over HTTP.
- The gateway can use `COLI_API_KEY` when exposed beyond localhost. JARVIS does not store, transmit, or log that value.
- Colibri serves one generation at a time and queues requests; it is unsuitable as an unattended agent executor.
- The repository contains build/download tooling and optional web/desktop components, so JARVIS does not run repository scripts or post-install hooks.
- No telemetry, microphone access, or private-audio upload is required by the selected local API path. Model download and any intentionally non-local bind are separate user decisions.

## Integration decision

The added `integrations.colibri_adapter` is a text-only client. It never starts a subprocess, accesses arbitrary files, downloads a model, or executes returned text. `COLIBRI_ENABLED=false` and `COLIBRI_MODE=disabled` remain the production defaults. To use an independently audited local server later, explicitly set `COLIBRI_ENABLED=true`, `COLIBRI_MODE=http_api`, and retain a loopback `COLIBRI_BASE_URL`.

## Sources

- Repository and release: https://github.com/JustVugg/colibri
- Windows guidance: https://github.com/JustVugg/colibri/blob/main/docs/windows.md
- API reference: https://github.com/JustVugg/colibri/blob/main/docs/api.md
