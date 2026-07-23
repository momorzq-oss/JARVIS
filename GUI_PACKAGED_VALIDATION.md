# GUI Packaged Validation

Date: 2026-07-20

## Validated Target

- Executable: `release\JARVIS-GUI\JARVIS.exe`
- SHA-256: `7210C318BF0EDA12ECEEEBDB0896C0C63E3C5FF733ADF1ACC439F20C95192235`
- Mode: PyInstaller windowed onedir
- Hermes: disabled and not installed

## Result

The packaged cinematic PySide6 interface launched maximized, rendered at 1920x1080 without missing assets, exposed the real command field and controls, and shut down cleanly through the GUI exit button. The interface uses original procedural Qt graphics; no reference-image artwork, logos, fonts, icons, or character likenesses were copied.

## Real State Connections

- Capability summary displayed the live registry result: 163 total, 142 working, 21 requiring login.
- The center renders an original full armored sentinel with illuminated eyes, broad shoulder plates, segmented torso armor, state-driven energy paths, and a large orbital chest core.
- Subsystem indicators reflected voice, wake word, Whisper, Kimi K3, Hermes, DesktopAgent, browser, Office, memory, research, news, and settings state.
- The task panel and AI core reflected executing, paused, resumed, waiting-for-confirmation, completed, failed, recording, and idle states observed during validation.
- The timeline displayed real structured actions, permission scopes, risk levels, allowlist validation, confirmation requests/results, execution, and completion.
- Active applications reflected JARVIS-owned Downloads, browser, and Word resources.
- System metrics displayed live CPU, RAM, disk, network, and thread state. GPU remained `Unavailable` because no supported GPU metric provider was available.
- Hermes displayed `DISABLED`, not a fabricated online state.

## Interaction Results

- Typed Downloads open/close: passed.
- External Desktop File Explorer preservation: passed.
- `/selftest`: passed with 163 / 142 / 21.
- Exact live Word phrase: routed to `office_word.create_research_document` after a focused router correction.
- Pause/resume: backend task state paused and progress held, then resumed.
- Word live insertion: passed on retry after one transient upstream LLM draft returned empty.
- Save workflow: passed and verified at `%LOCALAPPDATA%\JARVIS\temp\Renewable Energy Report.docx`.
- Confirmation dialog: visible with action, target, reason, risk, exact effect, Approve Once, Deny, and Cancel Task.
- Deny: Word remained open and no close executed.
- Approve Once: one JARVIS-owned Word resource closed; external Explorer remained open.
- YouTube open/close: passed.
- Emergency stop: backend logged key/button release.
- Reduced-motion resources: packaged and covered by tests.
- Exit: no packaged JARVIS process remained.
- Acoustic voice path: 0.97 wake score followed by recording, transcription, real routing, and response.
- Voice loop soak: 75 seconds with zero false wakes, false transcriptions, or repeated prompts.
- Packaged command input: browser open and close executed through the real GUI field and ActionManager.

## Evidence

- `.test_tmp\final_corrected_gui.png`
- `.test_tmp\final_corrected_pause.json`
- `.test_tmp\final_corrected_live_retry.json`
- `.test_tmp\final_corrected_save.json`
- `.test_tmp\final_corrected_confirmation_dialog.json`
- `.test_tmp\final_corrected_confirmation_deny.json`
- `.test_tmp\final_corrected_confirmation_approve.json`
- `.test_tmp\final_corrected_browser.json`
- `.test_tmp\final_corrected_voice_startup.json`
- `.test_tmp\armored_sentinel_packaged.png`

## Limitations

- A real human-spoken packaged command was not performed in this automated session.
- Live research depends on external source and LLM availability; one attempt produced empty drafts before the successful retry.
- GPU metrics and unsupported live previews correctly remain `Unavailable`.

Release status: **NOT READY** until the required human-spoken packaged command succeeds.

## 2026-07-23 Recovery-Candidate Assignment Check

The existing full-command-recovery candidate kept its GUI responsive while it created a live University Assignment Word document. Mission-control routing correctly showed `university.assignment`, but the natural save follow-up was routed back into assignment creation and a later explicit `.docx` save request fell through to chat. Exact external COM recovery saved only the JARVIS-owned document under `.test_tmp`; the resulting document contained 129 words rather than the requested 300. The candidate shut down cleanly and source JARVIS relaunched responsively from the desktop shortcut.

Candidate GUI assignment result: **FAIL**. This candidate is stale relative to the source routing regression fix and remains unpromoted.
