"""Audio device selection, VoiceState, capture service and engine tests."""
import threading
import time
import numpy as np

from voice.voice_state import VoiceState
from voice.devices import resolve_microphone, _is_real_mic
from voice import devices as device_service
from voice.capture import AudioCaptureService
from voice.engine import VoiceEngine
from voice.listener import Listener


# ---- VoiceState ---------------------------------------------------------------
def test_voicestate_snapshot_has_all_keys():
    s = VoiceState()
    snap = s.snapshot()
    for key in ("microphone_available", "microphone_active", "selected_microphone",
                "speaker_available", "speaker_engine", "speaker_state",
                "wakeword_loaded", "wakeword_active", "whisper_loaded",
                "recording", "processing", "last_audio_error"):
        assert key in snap


def test_voicestate_update():
    s = VoiceState()
    s.update(microphone_active=True, selected_microphone="USB Mic", wakeword_score=0.9)
    snap = s.snapshot()
    assert snap["microphone_active"] is True
    assert snap["selected_microphone"] == "USB Mic"
    assert snap["wakeword_score"] == 0.9


# ---- device selection -----------------------------------------------------------
def test_audio_backend_requires_first_initialization_on_main_thread(monkeypatch):
    import sys

    monkeypatch.setattr(device_service, "_backend_module", None)
    monkeypatch.delitem(sys.modules, "sounddevice", raising=False)
    errors = []

    def initialize_from_worker():
        try:
            device_service.initialize_audio_backend()
        except Exception as exc:
            errors.append(str(exc))

    worker = threading.Thread(target=initialize_from_worker)
    worker.start()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert errors == [
        "audio backend is not initialized; initialize it on the main thread"
    ]


def _fake_devices():
    return [
        {"index": 0, "name": "Speakers (Realtek)", "host_api": "WASAPI",
         "input_channels": 0, "output_channels": 2, "default_samplerate": 48000},
        {"index": 1, "name": "Microphone (USB PnP)", "host_api": "MME",
         "input_channels": 2, "output_channels": 0, "default_samplerate": 44100},
        {"index": 2, "name": "Stereo Mix (monitor)", "host_api": "WDM-KS",
         "input_channels": 2, "output_channels": 0, "default_samplerate": 44100},
    ]


def test_device_enumeration_queries_host_apis_once(monkeypatch):
    calls = []

    class SoundDevice:
        @staticmethod
        def query_devices():
            return [
                {"name": "USB Mic", "hostapi": 0, "max_input_channels": 1,
                 "max_output_channels": 0, "default_samplerate": 48000},
                {"name": "Speakers", "hostapi": 1, "max_input_channels": 0,
                 "max_output_channels": 2, "default_samplerate": 48000},
            ]

        @staticmethod
        def query_hostapis(*args):
            calls.append(args)
            assert args == ()
            return [{"name": "MME"}, {"name": "WASAPI"}]

    monkeypatch.setattr(device_service, "_sd", lambda: SoundDevice())

    result = device_service.list_devices()

    assert [item["host_api"] for item in result] == ["MME", "WASAPI"]
    assert calls == [()]


def test_default_microphone_uses_direct_query_without_full_inventory(monkeypatch):
    default = {
        "index": 7, "name": "USB Microphone", "host_api": "DirectSound",
        "input_channels": 2, "output_channels": 0,
        "default_samplerate": 44100,
    }
    monkeypatch.setattr(device_service, "default_input_index", lambda: 7)
    monkeypatch.setattr(device_service, "_device_at", lambda index: default)
    monkeypatch.setattr(
        device_service, "list_devices",
        lambda: (_ for _ in ()).throw(AssertionError("full inventory used")),
    )

    selected, reason = device_service.resolve_microphone("default")

    assert selected == default
    assert reason == "default"


def test_real_mic_filter_excludes_speakers_and_monitor():
    devs = _fake_devices()
    assert _is_real_mic(devs[1]) is True
    assert _is_real_mic(devs[0]) is False   # speaker
    assert _is_real_mic(devs[2]) is False   # stereo mix monitor


def test_resolve_microphone_saved_valid(monkeypatch):
    monkeypatch.setattr("voice.devices.list_devices", _fake_devices)
    mic, note = resolve_microphone(saved="1")
    assert mic["name"] == "Microphone (USB PnP)"
    assert note == "saved"


def test_resolve_microphone_invalid_saved_falls_back(monkeypatch):
    monkeypatch.setattr("voice.devices.list_devices", _fake_devices)
    monkeypatch.setattr("voice.devices.default_input_index", lambda: 1)
    mic, note = resolve_microphone(saved="999")   # does not exist
    assert mic is not None and mic["input_channels"] > 0
    assert note in ("default", "first")


def test_resolve_microphone_never_picks_speaker(monkeypatch):
    only_speakers = [
        {"index": 0, "name": "Speakers", "host_api": "WASAPI",
         "input_channels": 0, "output_channels": 2, "default_samplerate": 48000},
    ]
    monkeypatch.setattr("voice.devices.list_devices", lambda: only_speakers)
    monkeypatch.setattr("voice.devices.default_input_index", lambda: None)
    mic, note = resolve_microphone()
    assert mic is None


# ---- capture service --------------------------------------------------------------
def test_capture_subscribe_unsubscribe():
    cap = AudioCaptureService(device_index=None)
    calls = []
    cb = lambda a: calls.append(a)
    cap.subscribe(cb)
    assert cb in cap._subscribers
    cap.unsubscribe(cb)
    assert cb not in cap._subscribers


def test_capture_callback_distributes_to_subscribers():
    cap = AudioCaptureService(device_index=None)
    received = []
    cap.subscribe(lambda a: received.append(len(a)))
    frame = np.zeros(1280, dtype=np.int16)
    cap._callback(frame.tobytes(), 1280, None, None)
    assert received == [1280]
    assert cap.level >= 0.0


def test_capture_callback_defers_stream_status_logging(monkeypatch):
    cap = AudioCaptureService(device_index=None)
    monkeypatch.setattr(
        "voice.capture.audio_log.log",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("real-time callback attempted file I/O")
        ),
    )

    frame = np.zeros(1280, dtype=np.int16)
    cap._callback(frame.tobytes(), 1280, None, "input overflow")

    assert "input overflow" in cap.consume_stream_status(interval_seconds=0)
    assert cap.consume_stream_status(interval_seconds=0) == ""


def test_capture_start_failure_sets_error(monkeypatch):
    cap = AudioCaptureService(device_index=9999)
    import sounddevice as sd

    def boom(**kwargs):
        raise RuntimeError("no such device")
    monkeypatch.setattr(sd, "InputStream", boom)
    ok = cap.start()
    assert ok is False
    assert cap.running is False
    assert "no such device" in cap.last_error


def test_capture_uses_buffered_windows_input_stream(monkeypatch):
    cap = AudioCaptureService(device_index=1)
    captured = {}
    import sounddevice as sd

    class Stream:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def start(self):
            return None

        def stop(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(sd, "InputStream", Stream)
    monkeypatch.setattr(sd, "query_devices", lambda *_args, **_kwargs: {"name": "test mic"})

    assert cap.start() is True
    assert captured["latency"] == "high"
    assert captured["blocksize"] == 1280
    cap.stop()


def test_listener_initializes_vad_without_whisper_preload():
    listener = Listener()
    assert listener._model is None
    assert listener._vad is not None


def test_speaker_defers_native_device_probe_until_use(monkeypatch):
    from voice.speaker import Speaker
    probes = []
    monkeypatch.setattr(Speaker, "_init_playback", lambda self: probes.append(True))
    speaker = Speaker()
    assert speaker._ready is False
    assert probes == []


# ---- engine worker lifetime ----------------------------------------------------------
def test_engine_marks_mic_off_when_capture_fails(monkeypatch):
    from voice.speech_service import SpeechOutputService
    state = VoiceState()
    speech = SpeechOutputService(None, state)
    ctl = type("C", (), {"ctx": type("X", (), {"listener": None})(),
                         "_set_state": lambda s, a, b=None: None,
                         "_emit": lambda s, *a: None})()
    eng = VoiceEngine(ctl, state, speech, device_index=None)
    eng._wake = type(
        "Wake",
        (),
        {"_ensure_loaded": lambda self: True, "load_error": ""},
    )()
    monkeypatch.setattr(eng.capture, "start", lambda: False)
    monkeypatch.setattr(type(eng.capture), "last_error", "boom", raising=False)
    ok = eng.start()
    assert ok is False
    assert state.microphone_active is False
    assert state.last_audio_error


def test_wake_model_is_ready_before_microphone_stream_opens(monkeypatch):
    from voice.speech_service import SpeechOutputService

    events = []
    state = VoiceState()
    speech = SpeechOutputService(None, state)
    ctl = type(
        "C",
        (),
        {
            "ctx": type("X", (), {"listener": None})(),
            "_set_state": lambda self, *args: None,
            "_emit": lambda self, *args: None,
        },
    )()
    eng = VoiceEngine(ctl, state, speech, device_index=None)
    eng._wake = type(
        "Wake",
        (),
        {
            "_ensure_loaded": lambda self: events.append("wake_ready") or True,
            "load_error": "",
        },
    )()
    monkeypatch.setattr(
        eng.capture,
        "start",
        lambda: events.append("microphone_open") or False,
    )

    assert eng.start() is False
    assert events == ["wake_ready", "microphone_open"]


def test_stop_during_wake_load_never_opens_microphone(monkeypatch):
    from voice.speech_service import SpeechOutputService

    load_started = threading.Event()
    release_load = threading.Event()
    capture_starts = []
    result = []
    state = VoiceState()
    speech = SpeechOutputService(None, state)
    ctl = type(
        "C",
        (),
        {
            "ctx": type("X", (), {"listener": None})(),
            "_set_state": lambda self, *args: None,
            "_emit": lambda self, *args: None,
        },
    )()
    engine = VoiceEngine(ctl, state, speech, device_index=None)

    class Wake:
        load_error = ""

        def _ensure_loaded(self):
            load_started.set()
            release_load.wait(timeout=2)
            return True

    engine._wake = Wake()
    monkeypatch.setattr(
        engine.capture, "start",
        lambda: capture_starts.append(True) or True,
    )
    thread = threading.Thread(target=lambda: result.append(engine.start()))
    thread.start()
    assert load_started.wait(timeout=1)

    engine.stop()
    release_load.set()
    thread.join(timeout=2)

    assert result == [False]
    assert capture_starts == []
    assert engine.running is False
    assert state.microphone_active is False


def test_engine_thread_retained_as_attribute():
    from voice.speech_service import SpeechOutputService
    state = VoiceState()
    speech = SpeechOutputService(None, state)
    ctl = type("C", (), {"ctx": type("X", (), {"listener": None})(),
                         "_set_state": lambda s, a, b=None: None,
                         "_emit": lambda s, *a: None})()
    eng = VoiceEngine(ctl, state, speech, device_index=None)
    # worker/thread references are instance attributes (not local/garbage-collected)
    assert hasattr(eng, "_thread")
    assert hasattr(eng, "capture")
    assert hasattr(eng, "_stop")


def test_engine_reuses_preloaded_wake_model():
    state = VoiceState()
    speech = type("Speech", (), {"speaking": False})()
    controller = type(
        "Controller",
        (),
        {
            "ctx": type("Context", (), {"listener": None})(),
            "_set_state": lambda self, *args: None,
            "_emit": lambda self, *args: None,
        },
    )()
    wake = object()

    engine = VoiceEngine(controller, state, speech, wake_engine=wake)

    assert engine._wake is wake


def test_engine_timeout_does_not_start_recording():
    state = VoiceState()
    speech = type("Speech", (), {"speaking": False})()
    controller = type(
        "Controller",
        (),
        {
            "ctx": type("Context", (), {"listener": None})(),
            "_set_state": lambda self, *args: None,
            "_emit": lambda self, *args: None,
        },
    )()
    engine = VoiceEngine(controller, state, speech)
    recording_calls = []

    class TimeoutEvent:
        def wait(self, _timeout):
            engine._stop.set()
            return False

        def clear(self):
            return None

    engine._wake_event = TimeoutEvent()
    engine._record_command = lambda: recording_calls.append(True)
    engine._run()
    assert recording_calls == []


def test_wake_detection_is_suppressed_during_speech():
    state = VoiceState()
    speech = type("Speech", (), {"speaking": True})()
    emissions = []
    controller = type(
        "Controller",
        (),
        {
            "ctx": type("Context", (), {"listener": None})(),
            "_set_state": lambda self, *args: None,
            "_emit": lambda self, *args: emissions.append(args),
        },
    )()
    engine = VoiceEngine(controller, state, speech)
    wake_calls = []
    engine._wake = type(
        "Wake",
        (),
        {"process": lambda self, _audio: wake_calls.append(True) or 1.0},
    )()
    engine._on_wake_frame(np.zeros(1280, dtype=np.int16))
    assert wake_calls == []
    assert not engine._wake_event.is_set()
    assert emissions == []


def test_voice_engine_does_not_repeat_controller_response():
    """The controller/main pipeline owns normal response playback exactly once."""
    state = VoiceState()
    spoken = []
    speech = type("Speech", (), {"speak": lambda self, text: spoken.append(text)})()
    listener = type("Listener", (), {"preload": lambda self: None})()
    controller = type(
        "Controller",
        (),
        {
            "ctx": type("Context", (), {"listener": listener})(),
            "handle_text": lambda self, text, from_voice=False: "One response only.",
            "_set_state": lambda self, *args: None,
            "_emit": lambda self, *args: None,
        },
    )()
    engine = VoiceEngine(controller, state, speech)
    engine._listener = type("Transcriber", (), {"transcribe": lambda self, audio: "hello"})()

    engine._do_transcription_and_route(np.zeros(1280, dtype=np.int16))

    assert spoken == []


def test_wake_detection_is_deduplicated_for_active_session():
    state = VoiceState()
    speech = type("Speech", (), {"speaking": False})()
    emissions = []
    controller = type(
        "Controller",
        (),
        {
            "ctx": type("Context", (), {"listener": None})(),
            "_set_state": lambda self, *args: None,
            "_emit": lambda self, *args: emissions.append(args),
        },
    )()
    engine = VoiceEngine(controller, state, speech, threshold=0.5)
    wake_calls = []
    engine._wake = type(
        "Wake",
        (),
        {"process": lambda self, _audio: wake_calls.append(True) or 0.99},
    )()
    frame = np.zeros(1280, dtype=np.int16)
    engine._on_wake_frame(frame)
    engine._on_wake_frame(frame)
    assert wake_calls == [True]
    assert engine._wake_event.is_set()
    assert engine._wake_session_active.is_set()
    assert emissions == [("wakeword", "detected")]


def test_wake_frame_updates_live_audio_telemetry():
    state = VoiceState()
    speech = type("Speech", (), {"speaking": False})()
    controller = type(
        "Controller",
        (),
        {
            "ctx": type("Context", (), {"listener": None})(),
            "_set_state": lambda self, *args: None,
            "_emit": lambda self, *args: None,
        },
    )()
    engine = VoiceEngine(controller, state, speech, threshold=0.5)
    engine.capture._level = 0.42
    engine.capture._fps = 12.5
    engine._wake = type("Wake", (), {"process": lambda self, _audio: 0.2})()
    engine._on_wake_frame(np.zeros(1280, dtype=np.int16))
    snapshot = state.snapshot()
    assert snapshot["input_level"] == 0.42
    assert snapshot["frames_per_second"] == 12.5
    assert snapshot["wakeword_score"] == 0.2
    assert snapshot["wakeword_max_score"] == 0.2


def test_wake_inference_skips_silence_but_keeps_speech_hangover():
    state = VoiceState()
    speech = type("Speech", (), {"speaking": False})()

    class Vad:
        voiced = False

        def is_speech(self, _pcm, _rate):
            return self.voiced

    vad = Vad()
    listener = type("Listener", (), {"_vad": vad})()
    controller = type(
        "Controller",
        (),
        {
            "ctx": type("Context", (), {"listener": listener})(),
            "_set_state": lambda self, *args: None,
            "_emit": lambda self, *args: None,
        },
    )()
    engine = VoiceEngine(controller, state, speech)
    engine._listener = listener
    calls = []
    engine._wake = type(
        "Wake", (), {"process": lambda self, _audio: calls.append(True) or 0.0}
    )()
    frame = np.zeros(1280, dtype=np.int16)

    engine._on_wake_frame(frame)
    assert calls == []
    vad.voiced = True
    engine._on_wake_frame(frame)
    assert calls == [True]
    vad.voiced = False
    engine._on_wake_frame(frame)
    assert calls == [True, True]
    assert engine._wake_voice_hangover == 7


def test_capture_callback_queues_inference_without_blocking():
    state = VoiceState()
    speech = type("Speech", (), {"speaking": False})()
    controller = type(
        "Controller",
        (),
        {
            "ctx": type("Context", (), {"listener": None})(),
            "_set_state": lambda self, *args: None,
            "_emit": lambda self, *args: None,
        },
    )()
    engine = VoiceEngine(controller, state, speech)
    entered = threading.Event()
    release = threading.Event()
    engine._wake = type(
        "Wake",
        (),
        {"process": lambda self, _audio: entered.set() or release.wait(1) or 0.0},
    )()
    engine._wake_thread = threading.Thread(target=engine._wake_frame_loop, daemon=True)
    engine._wake_thread.start()
    frame = np.zeros(1280, dtype=np.int16)
    started = time.perf_counter()
    engine._enqueue_wake_frame(frame)
    elapsed = time.perf_counter() - started
    try:
        assert elapsed < 0.05
        assert entered.wait(timeout=1)
        # A full inference queue retains only recent audio and never blocks.
        for _ in range(10):
            engine._enqueue_wake_frame(frame)
        assert engine._wake_frames.qsize() <= 2
    finally:
        release.set()
        engine._stop.set()
        engine._wake_thread.join(timeout=1)


# ---- packaged resource lookup ------------------------------------------------------
def test_packaged_paths_are_frozen_safe():
    from config import Config
    # PIPER_MODEL resolves via RESOURCE_DIR (sys._MEIPASS when frozen)
    assert "piper" in str(Config.PIPER_MODEL).lower()
    assert Config.PLAYWRIGHT_BROWSERS_DIR is not None
