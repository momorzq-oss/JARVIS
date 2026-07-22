# Hermes Remaining Limitations

1. Official Hermes currently exposes broad terminal/tool/gateway functionality that is outside JARVIS's pilot boundary.
2. The official materials audited did not establish a stable structured planner API suitable for JARVIS to call safely.
3. Hermes is installed and diagnostics pass, but the first live zero-tool OpenRouter request was rate-limited (HTTP 429), so no structured plan has been validated.
4. No background execution is enabled; task records are JARVIS-side control state only.
5. Full regression test execution in this environment has 8 dependency-related failures (not Hermes failures): missing `sounddevice`, `openai`, `pyautogui`, `feedparser`, `requests`, and `pygetwindow` in Python 3.14.
6. Packaging and safe pilots remain blocked. Promotion is not recommended.
