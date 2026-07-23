from pathlib import Path
import queue
import wave

import pytest

from main import _parse_args
from voice.speaker import Speaker, _clean_for_speech


def test_speech_cleanup_removes_markdown_and_urls():
    text = _clean_for_speech("**Status:** [report](https://example.com) is ready.")
    assert text == "Status: report is ready."


def test_skip_model_preload_flag():
    assert _parse_args(["--skip-model-preload"]).skip_model_preload is True


def test_speaker_synthesizes_with_piper_only(monkeypatch, tmp_path):
    speaker = Speaker.__new__(Speaker)
    speaker.last_engine = ""

    piper_path = tmp_path / "piper.wav"
    monkeypatch.setattr(speaker, "_temp_path", lambda suffix: piper_path)

    def synth_piper(text, path):
        path.write_bytes(b"RIFF" + b"0" * 64)

    monkeypatch.setattr(speaker, "_synth_piper", synth_piper)

    output = speaker._synthesize("hello")
    assert output.name == "piper.wav"
    assert speaker.last_engine == "piper"


def test_speaker_collects_audio_from_persistent_piper_worker(monkeypatch, tmp_path):
    from config import Config

    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    monkeypatch.setattr(Config, "PIPER_MODEL", model)
    speaker = Speaker()
    speaker._piper_worker_dir = tmp_path / "worker"
    speaker._piper_worker_dir.mkdir()
    messages = queue.Queue()
    generated = speaker._piper_worker_dir / "123.wav"

    class Stdin:
        def write(self, text):
            assert text == "hello\n"
            generated.write_bytes(b"RIFF" + b"0" * 64)
            messages.put(f"INFO:__main__:Wrote {generated}")

        def flush(self):
            return None

    class Process:
        stdin = Stdin()
        returncode = None

        @staticmethod
        def poll():
            return None

    speaker._piper_process = Process()
    speaker._piper_messages = messages
    monkeypatch.setattr(speaker, "_piper_executable", lambda: tmp_path / "piper.exe")
    monkeypatch.setattr(speaker, "_start_piper_worker", lambda *_args: None)

    target = tmp_path / "result.wav"
    speaker._synth_piper("hello", target)

    assert target.read_bytes().startswith(b"RIFF")
    assert not generated.exists()


def test_speaker_collects_completed_wav_when_worker_log_is_delayed(monkeypatch, tmp_path):
    from config import Config

    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    monkeypatch.setattr(Config, "PIPER_MODEL", model)
    speaker = Speaker()
    speaker._piper_worker_dir = tmp_path / "worker"
    speaker._piper_worker_dir.mkdir()
    generated = speaker._piper_worker_dir / "quiet-worker.wav"

    class Stdin:
        def write(self, _text):
            with wave.open(str(generated), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(b"\x00\x00" * 160)

        def flush(self):
            return None

    class Process:
        stdin = Stdin()
        returncode = None

        @staticmethod
        def poll():
            return None

    speaker._piper_process = Process()
    speaker._piper_messages = queue.Queue()
    monkeypatch.setattr(speaker, "_piper_executable", lambda: tmp_path / "piper.exe")
    monkeypatch.setattr(speaker, "_start_piper_worker", lambda *_args: None)

    target = tmp_path / "result.wav"
    speaker._synth_piper("hello", target)

    with wave.open(str(target), "rb") as collected:
        assert collected.getnframes() == 160


def test_speaker_retries_windows_sharing_violation(monkeypatch, tmp_path):
    import voice.speaker as speaker_module

    speaker = Speaker()
    speaker._piper_worker_dir = tmp_path
    generated = tmp_path / "still-open.wav"
    target = tmp_path / "collected.wav"
    generated.write_bytes(b"RIFF" + b"0" * 64)
    locked = PermissionError(13, "in use", str(generated))
    locked.winerror = 32
    calls = []

    def replace(source, destination):
        calls.append((source, destination))
        if len(calls) == 1:
            raise locked
        Path(destination).write_bytes(Path(source).read_bytes())
        Path(source).unlink()

    monkeypatch.setattr(speaker_module.os, "replace", replace)

    assert speaker._collect_worker_file(generated, target) is False
    assert speaker._collect_worker_file(generated, target) is True
    assert target.exists()


def test_speaker_worker_launch_is_hidden_and_never_uses_shell(monkeypatch, tmp_path):
    from config import Config
    import voice.speaker as speaker_module

    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    monkeypatch.setattr(Config, "PIPER_MODEL", model)
    executable = tmp_path / "piper.exe"
    executable.write_bytes(b"exe")
    captured = {}

    class Process:
        stdin = None
        stderr = ()

        @staticmethod
        def poll():
            return None

    def popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(speaker_module.subprocess, "Popen", popen)
    speaker = Speaker()
    speaker._piper_worker_dir = tmp_path / "worker"

    speaker._start_piper_worker(executable, model)

    assert captured["kwargs"]["shell"] is False
    assert captured["args"][:3] == [str(executable), "--model", str(model)]
    if speaker_module.os.name == "nt":
        assert captured["kwargs"]["creationflags"] & speaker_module.subprocess.CREATE_NO_WINDOW


def test_packaged_speaker_prefers_bundled_piper_executable(monkeypatch, tmp_path):
    import voice.speaker as speaker_module

    bundled = tmp_path / "piper.exe"
    bundled.write_bytes(b"exe")
    monkeypatch.setattr(speaker_module.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(speaker_module.shutil, "which", lambda _name: None)

    assert Speaker._piper_executable() == bundled.resolve()


def test_frozen_synthesis_closes_stdin_and_collects_audio(monkeypatch, tmp_path):
    from config import Config
    import voice.speaker as speaker_module

    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    executable = tmp_path / "piper.exe"
    executable.write_bytes(b"exe")
    monkeypatch.setattr(Config, "PIPER_MODEL", model)
    monkeypatch.setattr(speaker_module.sys, "frozen", True, raising=False)
    speaker = Speaker()
    speaker._piper_worker_dir = tmp_path / "worker"
    captured = {}

    class Process:
        pid = 42
        returncode = 0

        def communicate(self, input=None, timeout=None):
            captured["input"] = input
            captured["timeout"] = timeout
            input_index = captured["args"].index("--input-file") + 1
            captured["input_text"] = Path(captured["args"][input_index]).read_text(
                encoding="utf-8"
            )
            generated = speaker._piper_worker_dir / "123.wav"
            generated.write_bytes(b"RIFF" + b"0" * 64)
            return "", f"INFO:__main__:Wrote {generated}"

    def popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(speaker_module.subprocess, "Popen", popen)
    monkeypatch.setattr(speaker, "_piper_executable", lambda: executable)
    target = tmp_path / "result.wav"

    speaker._synth_piper("hello", target)

    assert captured["input"] is None
    assert captured["input_text"] == "hello\n"
    assert captured["timeout"] == 120
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["stdin"] is speaker_module.subprocess.DEVNULL
    assert "--input-file" in captured["args"]
    assert target.read_bytes().startswith(b"RIFF")


def test_speaker_close_terminates_only_owned_piper_worker():
    events = []

    class Process:
        stdin = None

        @staticmethod
        def poll():
            return None

        @staticmethod
        def terminate():
            events.append("terminate")

        @staticmethod
        def wait(timeout=None):
            events.append(("wait", timeout))
            return 0

    speaker = Speaker()
    speaker._piper_process = Process()
    speaker.close()

    assert events == ["terminate", ("wait", 3)]
    assert speaker._piper_process is None


def test_packaging_excludes_cloud_tts_engines():
    from config import Config

    spec = (Config.SOURCE_DIR / "JARVIS-GUI.spec").read_text(encoding="utf-8")
    assert "collect_all('edge_tts')" not in spec
    assert "'edge_tts'" in spec
    assert "elevenlabs" not in spec.lower()


def test_onnx_only_packaging_excludes_unused_torch_runtime():
    from config import Config

    spec = (Config.SOURCE_DIR / "JARVIS-GUI.spec").read_text(encoding="utf-8")
    assert "if not _local_router:" in spec
    assert "excluded_modules += ['torch', 'torchvision', 'torchaudio']" in spec


def test_wakeword_process_returns_real_model_score():
    import numpy as np
    from voice.wakeword import WakeWordEngine

    engine = WakeWordEngine(model_name="hey_jarvis", threshold=0.5)
    engine._model = type(
        "Model",
        (),
        {"predict": lambda self, _audio: {"hey_jarvis": 0.73}},
    )()
    assert engine.process(np.zeros(1280, dtype=np.int16)) == pytest.approx(0.73)
