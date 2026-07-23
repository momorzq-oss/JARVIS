# JARVIS Windows Control Report

Date: 2026-07-20

## Services

- Unified service: `core/windows_controller.py`.
- Application discovery: `core/application_registry.py`.
- Session ownership: `core/registry.py`.
- Deterministic target resolution: `skills/windows_targets.py`.

## Supported Operations

`open_application`, `open_folder`, `open_file`, `open_uri`, `find_windows`, `focus_window`, `minimize_window`, `maximize_window`, `restore_window`, `move_window`, `resize_window`, `close_window`, `close_application`, `close_resource`, `close_recent_jarvis_item`, and `close_all_jarvis_items`.

## Known Locations

Desktop, Downloads, Documents, Pictures, Videos, Music, Home/User Profile, OneDrive, OneDrive Desktop, AppData, Local AppData, Recent Files, Startup, the JARVIS project, This PC, Recycle Bin, and Network.

Downloads uses the Windows Known Folder API first and `%USERPROFILE%\Downloads` only as a fallback.

## Applications

- Discovered: 154.
- Installed/launchable: 153.
- Required-list exception: Media Player was not detected.
- Word, Excel, PowerPoint, Outlook, OneNote, Edge, Chrome, Notepad, Calculator, Explorer, Settings, Task Manager, Paint, Snipping Tool, Terminal, PowerShell, Command Prompt, and Control Panel were detected.

## Ownership Safety

- Every new runtime receives a unique runtime session identifier.
- Persisted entries from earlier runtimes are not treated as currently owned.
- Application and folder launches snapshot existing HWNDs and associate only newly appearing windows.
- Unverified ownership is never closed by title or process fallback.
- Named close no longer scans and terminates unrelated matching processes.

## Live Results

- Downloads: opened correct path; Word did not start; folder closed by owned HWND.
- Word: opened by owned PID and closed successfully.
- Browser: real YouTube page loaded; context closed; registry empty.
- Close all: five owned entries closed; all pre-existing visible Notepad and Chrome HWNDs remained alive.

## 2026-07-23 Contextual Close Regression

The shared request scaffold now removes trailing polite suffixes even when punctuation separates them from the command. A live request opened one new Downloads Explorer HWND; `Close it again, please.` resolved to `__recent_folder__` and closed only that owned window. The pre-existing shell window and user Word and Chrome sessions remained alive. Automated coverage includes the same route plus `Would you close that for me?`.

Calculator live validation exercised `Please launch Calculator for me.`, `Could you minimize it for me?`, `Bring it back to the front, please.`, and `Would you close it for me?`. Windows briefly exposed both a shared `ApplicationFrameHost.exe` frame and a replacement `CalculatorApp.exe` CoreWindow. JARVIS now records the exact dedicated child PID and creation time, closes only that verified process identity after its host frame hides, and leaves zero Calculator windows. The protected user Word and Chrome processes remained alive and JARVIS stayed responsive. `Tell me the current time, please.` now reaches deterministic smalltalk through shared politeness normalization and produces exactly one Piper playback. The complete suite reports 606 collected, 606 passed, 0 failed, and 0 skipped.
