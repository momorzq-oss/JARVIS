# JARVIS shared router recovery

The command pipeline now uses one deterministic route for typed and voice-cleaned input before local-model or cloud fallback. The repaired route covers flexible date requests, voice lifecycle controls, local file search, background orchestration, existing folder/application/browser/Office/research aliases, and contextual save/close follow-ups.

Regression coverage is in `tests/test_router.py` and `tests/test_command_pipeline.py`. The current suite result is 715 passed, 0 failed, 0 skipped.
