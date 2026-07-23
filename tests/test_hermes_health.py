from brain.hermes_health import hermes_health


class _Disabled:
    enabled = False
    mode = "disabled"


def test_health_is_truthful_when_disabled(monkeypatch, tmp_path):
    repo = tmp_path / "hermes-agent"
    python = repo / "venv" / "Scripts" / "python.exe"
    launcher = repo / "hermes"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    launcher.write_bytes(b"")

    Runtime = type("Runtime", (), {"installed": True, "repo": repo})

    monkeypatch.setattr("brain.hermes_health.HermesRuntimeManager", Runtime)
    status = hermes_health(_Disabled())

    assert status["status"] == "disabled"
    assert status["installed"] is True
    assert str(repo) in status["detail"]


def test_enabled_health_status_never_runs_diagnostic_without_explicit_probe(monkeypatch, tmp_path):
    repo = tmp_path / "hermes-agent"
    Runtime = type("Runtime", (), {"installed": True, "repo": repo})

    class Enabled:
        enabled = True
        mode = "cli"

        def diagnostic(self, _command):
            raise AssertionError("routine status must not launch Hermes")

    monkeypatch.setattr("brain.hermes_health.HermesRuntimeManager", Runtime)
    status = hermes_health(Enabled())

    assert status["status"] == "configured"
    assert status["installed"] is True


def test_explicit_health_probe_reports_constrained_pilot_not_fake_gateway(monkeypatch, tmp_path):
    repo = tmp_path / "hermes-agent"
    Runtime = type("Runtime", (), {"installed": True, "repo": repo})

    class Enabled:
        enabled = True
        mode = "cli"

        def diagnostic(self, command):
            assert command == "--help"
            return "Hermes help"

    monkeypatch.setattr("brain.hermes_health.HermesRuntimeManager", Runtime)
    status = hermes_health(Enabled(), probe=True)

    assert status["status"] == "ready_for_pilot"
    assert status["gateway"] == "OFFLINE"
    assert status["repository"] == str(repo)
