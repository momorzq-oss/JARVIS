from pathlib import Path

from core.save_workflow import PendingSaveRequest


def _request(save_callback=None):
    return PendingSaveRequest(
        task_id="task", document_type="Word",
        suggested_filename="Artificial Intelligence Research Report",
        suggested_extension=".docx", current_application="Microsoft Word",
        save_callback=save_callback,
    )


def test_complete_path_resolution(tmp_path):
    request = _request()
    path = request.resolve(str(tmp_path))
    assert path == tmp_path / "Artificial Intelligence Research Report.docx"


def test_overwrite_confirmation_flag(tmp_path):
    existing = tmp_path / "Artificial Intelligence Research Report.docx"
    existing.write_bytes(b"existing")
    request = _request()
    request.resolve(str(tmp_path))
    assert request.overwrite_required is True


def test_save_verifies_file_exists(tmp_path):
    def save(path):
        Path(path).write_bytes(b"docx")

    request = _request(save)
    request.resolve(str(tmp_path))
    assert request.save() is True
    assert Path(request.resolved_path).exists()


def test_jarvis_test_folder_alias(monkeypatch, tmp_path):
    monkeypatch.setattr("core.save_workflow.Config.TEMP_DIR", tmp_path / ".test_tmp")
    request = PendingSaveRequest("t", "Word", "Report", ".docx", "Word")
    resolved = request.resolve("Save it in the JARVIS .test_tmp folder")
    assert resolved == tmp_path / ".test_tmp" / "Report.docx"


def test_save_location_supports_a_safe_custom_filename(monkeypatch, tmp_path):
    monkeypatch.setattr("core.save_workflow.Config.TEMP_DIR", tmp_path / ".test_tmp")
    request = PendingSaveRequest("t", "Word", "Report", ".docx", "Word")

    resolved = request.resolve(
        "Save it in the JARVIS test folder as renewable energy assignment validation"
    )

    assert resolved == (
        tmp_path / ".test_tmp" / "renewable energy assignment validation.docx"
    )


def test_save_location_does_not_accept_path_characters_in_filename(monkeypatch, tmp_path):
    monkeypatch.setattr("core.save_workflow.Config.TEMP_DIR", tmp_path / ".test_tmp")
    request = PendingSaveRequest("t", "Word", "Report", ".docx", "Word")

    assert request.resolve(
        "Save it in the JARVIS test folder as ..\\outside"
    ) is None


def test_nested_folder_creation_is_disclosed(tmp_path):
    request = PendingSaveRequest("t", "Word", "Report", ".docx", "Word")
    request.resolve(str(tmp_path / "new" / "nested"))
    assert request.directory_creation_required is True


def test_save_failure_does_not_claim_success(tmp_path):
    def fail(_path):
        raise RuntimeError("save failed")

    request = _request(fail)
    request.resolve(str(tmp_path))
    try:
        request.save()
    except RuntimeError as exc:
        assert str(exc) == "save failed"
    else:
        raise AssertionError("save failure was swallowed")


def test_close_during_save_confirmation_keeps_document_pending(tmp_path):
    from types import SimpleNamespace

    from main import handle_pending

    saved = []
    request = PendingSaveRequest(
        task_id="task-1",
        document_type="Word",
        suggested_filename="Report",
        suggested_extension=".docx",
        current_application="Microsoft Word",
        save_callback=lambda path: saved.append(path),
    )
    request.resolved_path = str(tmp_path / "Report.docx")
    request.stage = "confirm"
    ctx = SimpleNamespace(
        pending={"kind": "save_document", "request": request},
    )

    handled, response = handle_pending("Close Word", ctx)

    assert handled is True
    assert "still unsaved" in response
    assert "say yes" in response.lower()
    assert saved == []
    assert ctx.pending["request"] is request
