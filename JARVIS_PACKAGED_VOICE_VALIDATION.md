# JARVIS Packaged Voice Validation

Date: 2026-07-20

## Target

- Executable: `release\JARVIS-GUI\JARVIS.exe`
- SHA-256: `7210C318BF0EDA12ECEEEBDB0896C0C63E3C5FF733ADF1ACC439F20C95192235`

## Automated Packaged Voice Startup

- Start Voice invoked through the packaged GUI.
- A real input device was enumerated and opened: USB PnP microphone.
- Wake-word worker started.
- `hey_jarvis` model loaded at threshold 0.5.
- Voice engine thread started.
- GUI entered listening/recording state from live microphone state.
- No `WakeWordEngine.process()` missing-method or wake processing error appeared.
- Stop Voice closed the microphone stream and worker cleanly.
- Final application exit stopped voice workers again and completed controller shutdown.

Result: **PASS** for packaged microphone, wake-word startup, GUI voice state, and clean stop.

## Loop And Command Repair

- Fixed the five-second wake wait timeout being treated as a real wake event.
- Suppressed wake inference while Piper is speaking and during an active command session.
- Initialized WebRTC VAD independently of Whisper preload so `--skip-model-preload` can still record commands.
- Restored the active USB microphone gain and selected it explicitly in the persisted JARVIS settings.
- Packaged acoustic wake score reached `0.97` at the configured `0.50` threshold.
- The packaged app recorded speech, produced a 24-character transcription, sent it through the real router, and returned a response.
- A subsequent 75-second normal-mode soak produced zero false wakes, zero false transcriptions, and no repeated Piper prompts.

Result: **PASS** for packaged acoustic wake, recording, transcription, routing, response, and loop suppression.

## Confirmation Speech Coverage

Automated tests passed for voice `yes`, `no`, and `cancel` while a confirmation was pending. These tests validate controller routing and safe execution behavior but are not a substitute for a human-spoken packaged command.

## Human-Spoken Validation

No real human-spoken command was performed in this automated session. The end-to-end result above used an operating-system speech synthesizer played through the real speakers and captured by the real microphone.

Human voice result: **NOT EXECUTED**.

Release status: **NOT READY** until at least one required command is spoken by a human through the packaged executable and its transcript-to-action result is recorded.

## 2026-07-23 Production and Candidate Revalidation

The untouched production executable retained SHA-256 `7210C318BF0EDA12ECEEEBDB0896C0C63E3C5FF733ADF1ACC439F20C95192235`. It launched responsive, opened the USB microphone, loaded `hey_jarvis`, and routed `What time is it?` locally. In this run it queued its greeting and typed-command response but started no Piper child process and logged no synthesis or playback completion within 40 seconds. Production typed-response TTS therefore fails the current validation and the prior PASS is not carried forward as present-tense evidence.

The existing unpromoted candidate `release\candidates\JARVIS-FULL-COMMAND-RECOVERY-20260723-100804\JARVIS\JARVIS.exe` retained SHA-256 `6EE9379F43F44C5EEE369768FBE159CC6CEF35A5A862E1B6FB383CDAE9D64461`. It launched responsive, loaded wake-word and microphone services, started its bundled frozen Piper worker, completed the greeting, then routed `What time is it?` locally and completed exactly one additional synthesis/playback with zero speech errors. No ElevenLabs-named file exists in either distribution.

Current result: **PRODUCTION FAIL / EXISTING CANDIDATE PASS / NOT PROMOTED**. A new candidate remains blocked by the mandatory real Hermes structured-plan and packaged-pilot gate.
