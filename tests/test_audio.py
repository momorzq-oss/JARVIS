"""Audio device selection, VoiceState, capture service and engine tests."""
import threading
import numpy as np

from voice.voice_state import VoiceState
from voice.devices import resolve_microphone, _is_real_mic
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
def _fake_devices():
    return [
        {"index": 0, "name": "Speakers (Realtek)", "host_api": "WASAPI",
         "input_channels": 0, "output_channels": 2, "default_samplerate": 48000},
        {"index": 1, "name": "Microphone (USB PnP)", "host_api": "MME",
         "input_channels": 2, "output_channels": 0, "default_samplerate": 44100},
        {"index": 2, "name": "Stereo Mix (monitor)", "host_api": "WDM-KS",
         "input_channels": 2, "output_channels": 0, "default_samplerate": 44100},
    ]


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


def test_listener_initializes_vad_without_whisper_preload():
    listener = Listener()
    assert listener._model is None
    assert listener._vad is not None


# ---- engine worker lifetime ----------------------------------------------------------
def test_engine_marks_mic_off_when_capture_fails(monkeypatch):
    from voice.speech_service import SpeechOutputService
    state = VoiceState()
    speech = SpeechOutputService(None, state)
    ctl = type("C", (), {"ctx": type("X", (), {"listener": None})(),
                         "_set_state": lambda s, a, b=None: None,
                         "_emit": lambda s, *a: None})()
    eng = VoiceEngine(ctl, state, speech, device_index=None)
    monkeypatch.setattr(eng.capture, "start", lambda: False)
    monkeypatch.setattr(type(eng.capture), "last_error", "boom", raising=False)
    ok = eng.start()
    assert ok is False
    assert state.microphone_active is False
    assert state.last_audio_error


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


# ---- packaged resource lookup ------------------------------------------------------
def test_packaged_paths_are_frozen_safe():
    from config import Config
    # PIPER_MODEL resolves via RESOURCE_DIR (sys._MEIPASS when frozen)
    assert "piper" in str(Config.PIPER_MODEL).lower()
    assert Config.PLAYWRIGHT_BROWSERS_DIR is not None
