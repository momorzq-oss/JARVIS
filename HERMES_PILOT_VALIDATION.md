# Hermes Pilot Validation

Hermes was installed externally and live zero-tool planning requests were attempted using the official `hermes chat --quiet --query` machine-readable path, `--safe-mode`, a one-turn limit, the official empty `context_engine` toolset, `openrouter`, and `openai/gpt-oss-safeguard-20b`. The latest official request diagnostic records HTTP 429 from provider Groq after Hermes exhausted its retries. No model response or protocol JSON plan was produced. No JARVIS action, file, background task, or speech output was created.

The JARVIS-side protocol, adapter, health, task, and Colibri tests pass. The protocol rejects a blocked capability and shell text, and task records support pause, resume, cancellation, and a two-task concurrency bound. UTF-8 output is decoded explicitly, decorated CLI output is never parsed, and every retry left zero Hermes processes and no listener on port 9119.

Live Hermes plan acceptance, Hermes-driven Word output, real GUI Hermes progress, Piper completion speech for a Hermes task, and emergency interruption of a running Hermes request remain unvalidated because the provider request was rate-limited. JARVIS's own live pause/resume/cancel/emergency fan-out is independently validated. A future retry remains safe only through the constrained adapter and only after the OpenRouter account permits the configured model.
