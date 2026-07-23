"""Regression checks for deterministic desktop process lifecycle controls."""

from desktop_main import (
    _auto_voice_requested,
    _parse_args,
    _queue_deferred_capability_scan,
    _run_background_startup,
    _startup_preload_enabled,
)


def test_cold_wake_preload_never_blocks_mission_control_construction():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "desktop_main.py").read_text(
        encoding="utf-8"
    )
    controller_builder = source.split("    def build_controller():", 1)[1].split(
        "    with concurrent.futures.ThreadPoolExecutor", 1
    )[0]

    assert "preload_wake_model" not in controller_builder


def test_diagnostic_launch_can_disable_saved_auto_voice():
    args = _parse_args([
        "--skip-model-preload", "--no-auto-voice",
        "--exit-after-seconds", "2.5",
    ])

    assert args.skip_model_preload is True
    assert args.no_auto_voice is True
    assert args.start_voice is False
    assert args.exit_after_seconds == 2.5
    assert _startup_preload_enabled(args) is False
    assert _auto_voice_requested(args, {"start_voice_automatically": True}) is False


def test_explicit_voice_request_survives_diagnostic_saved_setting_override():
    args = _parse_args(["--start-voice", "--no-auto-voice"])

    assert _auto_voice_requested(args, {"start_voice_automatically": False}) is True


def test_background_startup_makes_voice_ready_before_optional_scans():
    events = []

    class Signal:
        def __init__(self, name):
            self.name = name

        def emit(self, *args):
            events.append((self.name, *args))

    class Controller:
        def apply_settings(self):
            events.append(("apply",))

        def start_voice(self):
            events.append(("voice",))
            return True

        def preload_models(self):
            events.append(("preload",))

        def start_capability_scan(self):
            events.append(("scan",))

    bridge = type("Bridge", (), {
        "statusChanged": Signal("status"),
        "autoVoiceStarted": Signal("auto_voice"),
        "registry": Signal("registry"),
        "startupCompleted": Signal("complete"),
    })()

    _run_background_startup(
        Controller(), bridge, lambda: [],
        auto_voice_requested=True, preload_enabled=True,
    )

    names = [event[0] for event in events]
    assert names.index("voice") < names.index("apply")
    assert names.index("apply") < names.index("preload") < names.index("scan")
    assert ("auto_voice", True) in events


def test_auto_voice_startup_can_defer_noncritical_capability_scan():
    events = []

    class Signal:
        def __init__(self, name):
            self.name = name

        def emit(self, *args):
            events.append((self.name, *args))

    controller = type("Controller", (), {
        "start_voice": lambda self: events.append(("voice",)) or True,
        "apply_settings": lambda self: events.append(("apply",)) or True,
        "preload_models": lambda self: events.append(("preload",)),
        "start_capability_scan": lambda self: events.append(("scan",)),
    })()
    bridge = type("Bridge", (), {
        "statusChanged": Signal("status"),
        "autoVoiceStarted": Signal("auto_voice"),
        "registry": Signal("registry"),
        "startupCompleted": Signal("complete"),
    })()

    _run_background_startup(
        controller, bridge, lambda: [],
        auto_voice_requested=True, preload_enabled=False,
        run_capability_scan=False,
    )

    names = [event[0] for event in events]
    assert "voice" in names
    assert "scan" not in names
    assert "complete" in names


def test_deferred_capability_scan_runs_once_after_voice_settle_delay():
    scheduled = []
    events = []

    def schedule(delay_ms, callback):
        scheduled.append((delay_ms, callback))

    def run_async(callback):
        events.append("queued")
        callback()

    _queue_deferred_capability_scan(
        schedule, run_async, lambda: events.append("scan"),
    )

    assert events == []
    assert scheduled[0][0] == 20_000
    scheduled[0][1]()
    assert events == ["queued", "scan"]
