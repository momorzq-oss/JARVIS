# JARVIS Packaged Validation

Date: 2026-07-20

## Target

- `C:\Users\Burab\OneDrive\Desktop\JARVIS\release\JARVIS-GUI\JARVIS.exe`
- SHA-256: `7210C318BF0EDA12ECEEEBDB0896C0C63E3C5FF733ADF1ACC439F20C95192235`

## Results

| Check | Result | Evidence |
|---|---|---|
| Packaged-only startup | PASS | Process path and command line matched the release executable |
| No console window | PASS | Windowed PyInstaller build; only the Qt application window appeared |
| GUI/assets | PASS | Cinematic dashboard rendered with packaged QSS resources |
| Armored sentinel | PASS | Original full-torso robot rendered from packaged procedural Qt code |
| Capability registry | PASS | 163 total, 142 working, 21 requires login, 0 missing, 0 broken |
| `/help` | PASS | Registry command list returned |
| `/skills` | PASS | Dynamic registry category/connectivity summary returned |
| `/status` | PASS | Controller/session/capability state returned |
| `/capabilities` | PASS | Dynamic capability records returned |
| `/selftest` | PASS | 163 / 142 / 21 returned |
| Downloads open/close | PASS | Downloads Explorer opened and then closed |
| Ownership preservation | PASS | Externally opened Desktop Explorer remained open |
| Exact live Word routing | PASS | Structured `office_word.create_research_document` action used |
| Pause/resume | PASS | State became `PAUSED`; step held; task resumed |
| Word live creation | PASS | `Document1 - Word` opened after four real sources were gathered |
| Save workflow | PASS | File saved and verified under `%LOCALAPPDATA%\JARVIS\temp` |
| Confirmation dialog | PASS | Required action fields and three decisions were visible |
| Confirmation deny | PASS | Word stayed open; audit outcome was `denied` |
| Confirmation approve once | PASS | One owned Word item closed; audit outcome was `approved_once` |
| Confirmation cancel/close/timeout | PASS (automated suite) | Confirmation-flow tests passed; not repeated manually on final hash |
| Voice yes/no/cancel | PASS (automated suite) | Voice confirmation tests passed; not a human-spoken validation |
| YouTube open/close | PASS | Packaged response confirmed browser open and close |
| Emergency stop | PASS | Backend logged release of all keys/buttons |
| Audit logging | PASS | Requested, confirmation requested/result, execution, and result records written |
| Redaction | PASS | Automated redaction tests passed; dialog contained no secret values |
| Voice startup | PASS | Real microphone opened; wake model loaded; no missing `process()` error |
| Voice acoustic path | PASS | 0.97 wake score; recording, 24-character transcription, real routing, and response completed |
| Voice loop soak | PASS | 75 seconds in normal mode; zero false wakes, false transcriptions, or repeated prompts |
| Desktop adapter framework | PASS | Real Word, Excel, and PowerPoint files created visibly, verified, and closed safely |
| Browser adapter framework | PASS | Google search and YouTube search/play/pause completed visibly through Playwright |
| Packaged browser commands | PASS | GUI command field executed browser open/close and recorded both in the web action log |
| Clean shutdown | PASS | GUI exit completed; no JARVIS process remained |

## Live Word Detail

The exact required phrase first exposed a real routing defect in a pre-final package: it fell through to generic app opening and searched the web. `brain\router.py` received a minimal route for that phrase and `tests\test_windows_routing.py` received a regression test. The final package then produced the correct structured action.

One final-package live run found four sources but received empty draft text from the external LLM service. A retry of the same command completed, opened Word, inserted the report, requested a save location, and verified a 15,455-byte document at:

`C:\Users\Burab\AppData\Local\JARVIS\temp\Renewable Energy Report.docx`

## Audit Paths

- Packaged audit log: `%LOCALAPPDATA%\JARVIS\data\audit_log.json`
- Packaged command log: `%LOCALAPPDATA%\JARVIS\logs\commands.log`
- Packaged audio log: `%LOCALAPPDATA%\JARVIS\logs\audio.log`

## Remaining Blockers Before Hermes

- Hermes remains intentionally absent.
- No Hermes orchestration adapter, task lifecycle, or end-to-end Hermes tests exist yet.
- Multi-step Hermes sandboxing, budgets, rollback policy, and recovery policy still require a dedicated implementation phase.
- The prior Hermes readiness audit predates the completed action schema, allowlist, confirmation flow, and capability registry and should be rerun before integration.
- A real human-spoken packaged command must pass before this release is marked ready.

The final armored-sentinel hash was launched directly, completed packaged browser command validation, and retained the prior acoustic voice validation. The full source suite passed 250/250.

Final release classification: **NOT READY** pending human voice validation. Do not proceed to Hermes yet.

## 2026-07-23 Non-Destructive Revalidation

- Production hash remained `7210C318BF0EDA12ECEEEBDB0896C0C63E3C5FF733ADF1ACC439F20C95192235`.
- Production startup, screen bounds, responsiveness, wake-word loading, USB microphone, and deterministic time routing passed.
- Production typed-response Piper failed: no Piper worker, synthesis, playback start, or playback completion followed the command within 40 seconds.
- Existing candidate hash remained `6EE9379F43F44C5EEE369768FBE159CC6CEF35A5A862E1B6FB383CDAE9D64461`.
- Existing candidate startup initially displayed the truthful `JARVIS · Starting` shell, became responsive, completed bundled Piper greeting playback, and completed one typed time-response playback.
- Neither executable nor release directory was modified, promoted, or overwritten.
- The current source suite reports 624 collected, 624 passed, 0 failed, and 0 skipped.

Current production classification: **NOT READY**. Existing candidate classification: **AUDIO PASS, STILL UNPROMOTED** pending the remaining Hermes and full candidate gates.

## 2026-07-23 University Assignment Candidate Validation

- Validated the untouched recovery candidate at `release\candidates\JARVIS-FULL-COMMAND-RECOVERY-20260723-100804\JARVIS\JARVIS.exe`.
- `Write a 300-word APA 7 essay about renewable energy for undergraduate level live in Word.` correctly entered `university.assignment`, opened a JARVIS-owned Word document, added public references, and requested a save location.
- The natural save follow-up `Save it to ...\.test_tmp as packaged university assignment validation.` was misclassified as a new university assignment because the filename contained “university assignment”.
- After cancelling that mistaken pending state, an explicit `.docx` save request fell through to `chat` instead of completing the Word save workflow.
- Exact COM recovery preserved the JARVIS-owned document at `.test_tmp\packaged_university_validation.docx` without closing or modifying another Word document. This recovery was external validation work and is not counted as a packaged save pass.
- The recovered document was readable, contained 17 paragraphs, 129 words, a References heading, and six URL occurrences. It therefore also failed the requested 300-word output target.
- The candidate exited cleanly. The source desktop shortcut then launched source JARVIS successfully and its GUI became responsive.
- Source regression coverage already protects a pending save filename from restarting University Assignment Mode; the stale candidate predates that correction.

Existing candidate assignment classification: **FAIL — SAVE ROUTING AND WORD-COUNT TARGET**. The candidate remains unpromoted and must be rebuilt only after the mandatory Hermes gates pass.
