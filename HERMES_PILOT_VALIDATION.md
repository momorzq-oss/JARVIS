# Hermes Pilot Validation

Hermes was installed externally and a live zero-tool planning request was attempted using `--safe-mode`, the official empty `context_engine` toolset, `openrouter`, and `openai/gpt-oss-safeguard-20b`. OpenRouter returned HTTP 429 after three retries. No JSON plan, JARVIS action, file, background task, or speech output was created.

The JARVIS-side pilot safety checks passed: 16 targeted Hermes/Colibri tests passed. The protocol rejects a blocked capability and shell text, and task records support pause, resume, cancellation, and a two-task concurrency bound.

Live pilots, Word output, real GUI progress, Piper completion speech, and emergency interruption of a running Hermes request remain unvalidated because the provider request was rate-limited. A retry is safe only through the constrained adapter and only after the OpenRouter account permits the configured model.
