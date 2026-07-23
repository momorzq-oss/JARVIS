# Hermes Security Report

- Default state: `HERMES_ENABLED=false`, `HERMES_MODE=disabled`.
- Hermes v0.19.0 is installed externally at audited commit `32a9f2acbcc5c0da9e8e90ccd4c2c1189e5e5da6`; at rest no Hermes process, gateway, listener, schedule, learned skill, or external messaging integration is started.
- The adapter permits the audited `--help` and `doctor` diagnostics plus one official quiet CLI plan request when explicitly enabled. Planning forces safe mode, one turn, and the empty `context_engine` toolset. Every launch uses an argument list with `shell=False` and captured UTF-8 output.
- JARVIS accepts only pilot capability identifiers, never raw commands, executable paths, code, shell text, or input coordinates.
- The controller owns one adapter. `stop_task()`, shutdown, and emergency dispatch cancel its exact active process and descendants, clear adapter state, and cancel all Hermes task records in addition to existing automation/live-task stop paths.
- Piper remains the sole production speech service; no ElevenLabs dependency or configuration was introduced.

Regression evidence: 570 tests collected, 570 passed, 0 failed, 0 skipped. Blocking fake Hermes processes prove cancellation and timeout terminate and clear the owned process; emergency dispatch proves the controller stop fan-out is reached. Explicit health probing reports an offline gateway and never invents a running service. Settings migration rejects the unsupported legacy `managed` value, forces autonomous flags off, and passes only non-secret provider/model data to the live adapter.

Remaining gate: the real provider request returned HTTP 429 before a plan was produced. Hermes stays disabled and no candidate is promoted until a real protocol plan and the required safe pilots pass.
