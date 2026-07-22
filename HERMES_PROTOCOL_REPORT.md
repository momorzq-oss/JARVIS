# Hermes Protocol Report

`brain/hermes_protocol.py` defines protocol version 1.0 and validates only JSON plans. It rejects malformed JSON, wrong versions, unknown/blocked capabilities, skill-operation mismatches, missing scopes, unsafe risk metadata, duplicate step ids, over-limit plans, and shell/code text.

Returned plans remain data. `brain/hermes_orchestrator.py` creates a JARVIS task in `WAITING_CONFIRMATION`; it does not execute a desktop action. Execution must be implemented through existing trusted JARVIS capability handlers after confirmation and capability validation.
