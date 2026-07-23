# Hermes Remaining Limitations

1. Official Hermes currently exposes broad terminal/tool/gateway functionality that is outside JARVIS's pilot boundary.
2. The supported integration surface is the official quiet one-shot CLI; no stable structured planner HTTP API was identified.
3. Hermes is installed and diagnostics pass. One live zero-tool response was rejected for violating the exact response schema; three later exact-schema requests were rate-limited by provider Groq (HTTP 429). No structured plan has been accepted.
4. No background execution is enabled; task records are JARVIS-side control state only.
5. The complete supported Python 3.12 regression suite passes: 591 collected, 591 passed, 0 failed, 0 skipped.
6. The existing packaged candidate predates the latest routing and Hermes adapter fixes. A new Hermes candidate must not be built or promoted until a real plan validates and the required Hermes pilots pass. Promotion is not recommended yet.
