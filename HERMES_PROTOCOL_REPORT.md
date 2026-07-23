# Hermes Protocol Report

`brain/hermes_protocol.py` defines protocol version 1.0 and validates only JSON plans. It rejects malformed JSON, wrong versions, unknown/blocked capabilities, skill-operation mismatches, missing scopes, unsafe risk metadata, duplicate step ids, over-limit plans, and shell/code text.

The adapter narrows that protocol allowlist again for every request. A returned step is accepted only when its capability ID was present in that exact request, and its permission scope and risk level must match the supplied capability-registry metadata. Being on the broader pilot allowlist is not sufficient.

The orchestrator constructs that request subset from live registry records only. Records must be in the pilot set, connected, `WORKING`/`CONNECTED`, assigned a permission scope, and carry valid risk metadata. Approved steps re-enter JARVIS through `ActionManager`; the executor must return an explicit verified status before task progress advances. Research source reads additionally reject loopback, private, link-local, reserved, and otherwise non-public destinations.

Returned plans remain data. `brain/hermes_orchestrator.py` creates a JARVIS task in `WAITING_CONFIRMATION`; it does not execute a desktop action. Execution must be implemented through existing trusted JARVIS capability handlers after confirmation and capability validation.

The constrained adapter uses the official `hermes chat --quiet --query`
machine-readable one-shot mode, plus `--safe-mode`, one maximum turn, the
`tool` source tag, and the empty `context_engine` toolset.
Stdout is therefore treated only as a complete JSON document; JARVIS never
extracts executable instructions from decorated CLI prose.

The plan subprocess is controller-owned and polled with a bounded timeout.
Stop, shutdown, and emergency-stop paths terminate only that exact process and
its descendants, then clear adapter state. Diagnostics and planning never use
`shell=True` or parse prose into executable actions.
