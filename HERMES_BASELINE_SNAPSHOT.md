# Hermes/Colibri Baseline Snapshot

Created 2026-07-22 before the Hermes protocol pilot was added.

- Existing tracked working-tree changes were preserved: `config.py` and `tests/test_integration.py` already contained a user-selected OpenRouter model change.
- No existing executable was overwritten, rebuilt, moved, or packaged.
- No Hermes or Colibri executable, model, remote installer, dependency, or API key was installed or run.
- Piper, Whisper, and OpenWakeWord configuration were left in place.
- Baseline packaged executable: `release\\JARVIS-GUI\\JARVIS.exe`
- SHA-256: `7210C318BF0EDA12ECEEEBDB0896C0C63E3C5FF733ADF1ACC439F20C95192235`
- Baseline collection in the available environment: 254 tests collected.
- Backup created: `.backups\\before_hermes_integration_20260722_055513`.

The requested OpenRouter model default was updated to `openai/gpt-oss-safeguard-20b`; this is a safety-reasoning model and should be validated against the JARVIS conversation/research workload before any production promotion.
