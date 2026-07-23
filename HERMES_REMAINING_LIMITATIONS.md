# Hermes Remaining Limitations

1. Official Hermes currently exposes broad terminal/tool/gateway functionality that is outside JARVIS's pilot boundary.
2. The supported integration surface is the official quiet one-shot CLI; no stable structured planner HTTP API was identified.
3. Hermes is installed and diagnostics pass. One live zero-tool response was rejected for violating the exact response schema; five later exact-schema requests were rate-limited by provider Groq (HTTP 429). OpenRouter's official model page currently lists only one provider for `openai/gpt-oss-safeguard-20b`, so no same-model fallback endpoint exists. It also describes the model as a safety classification/filtering model rather than a general planning model. No structured plan has been accepted. Source: https://openrouter.ai/openai/gpt-oss-safeguard-20b
4. No unattended background execution is enabled. `/background` produces a reviewable plan only; an approved plan runs interactively through JARVIS's trusted execution boundary. Task records remain JARVIS-side control state.
5. The complete supported Python 3.12 regression suite passes: 693 collected, 693 passed, 0 failed, 0 skipped.
6. Thirteen of the nominal pilot capability IDs currently meet the live registry/health boundary. Unregistered pilot names stay hidden until real JARVIS adapters exist.
7. The existing packaged candidate predates the latest routing and Hermes adapter fixes. A new Hermes candidate must not be built or promoted until a real plan validates and the required Hermes pilots pass. Promotion is not recommended yet.
8. Cancellation is cooperative for a trusted operation already in flight. Its bounded return is discarded without progress, retries, or output metadata, but a side effect completed before the cancellation signal is not represented as rolled back.
