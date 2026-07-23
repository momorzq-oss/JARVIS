# Hermes Packaged Validation

A new Hermes candidate was intentionally not built. The supported Python 3.12 suite is complete at 606 collected, 606 passed, 0 failed, and 0 skipped. One real zero-tool response failed exact-schema validation and three later exact-schema requests returned HTTP 429, so the required Hermes pilots have not all passed.

Non-destructive package comparison on 2026-07-23 confirmed that the untouched production executable fails current typed-response Piper validation while the pre-existing full-command-recovery candidate completes bundled frozen-Piper greeting and command playback. This does not satisfy the Hermes candidate gate and neither build was promoted.

The existing recovery candidate at `release\candidates\JARVIS-FULL-COMMAND-RECOVERY-20260723-100804\JARVIS\JARVIS.exe` previously passed its startup, wake word, microphone, bundled Piper, emergency-stop, and clean-shutdown checks. Its SHA-256 is `6EE9379F43F44C5EEE369768FBE159CC6CEF35A5A862E1B6FB383CDAE9D64461`, but it predates the latest routing and Hermes cancellation changes and is not a Hermes release candidate.

The verified production executable was not overwritten or promoted. Packaged Hermes validation remains pending a real plan, safe execution pilot, GUI progress, Piper summary, emergency interruption, and rebuilt candidate validation.
