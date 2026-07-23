import json
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from config import Config
from core.action_manager import Action, ActionManager
from core.assistant_controller import AssistantController
from gui.workers import GuiController
from tests.test_controller import make_ctx
from voice.engine import VoiceEngine


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def confirmation_env(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "AUDIT_LOG_FILE", tmp_path / "audit_log.jsonl")
    controller = AssistantController(ctx=make_ctx(), skip_preload=True)
    gui = GuiController(controller=controller)
    gui.confirmation_timeout_ms = 500
    yield controller, gui
    gui.shutdown()


def _button(dialog, text):
    return next(
        button for button in dialog.findChildren(QPushButton)
        if button.text() == text
    )


def _run_confirmation(qapp, controller, gui, callback=None, timeout=2.0):
    executed = []
    result = []
    intent = {"skill": "app.close", "params": {"target": "__all__"}}

    def executor():
        executed.append(True)
        return "closed"

    thread = threading.Thread(
        target=lambda: result.append(
            controller.action_manager.execute_intent(intent, executor)
        ),
        daemon=True,
    )
    thread.start()
    if callback is not None:
        def invoke_when_visible():
            dialog = gui._confirmation_dialog
            if dialog is not None and dialog.isVisible():
                callback(dialog, thread, executed)
            elif thread.is_alive():
                QTimer.singleShot(5, invoke_when_visible)

        QTimer.singleShot(0, invoke_when_visible)
    deadline = time.time() + timeout
    while thread.is_alive() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    thread.join(timeout=0.2)
    assert not thread.is_alive()
    return result[0], executed


def test_gui_confirmation_appears_and_approve_once(qapp, confirmation_env):
    controller, gui = confirmation_env

    def approve(dialog, thread, executed):
        assert dialog is not None and dialog.isVisible()
        labels = " ".join(label.text() for label in dialog.findChildren(QLabel))
        for expected in ("Action Name", "Target", "Reason", "Risk Level", "Exact Effect"):
            assert expected in labels
        assert thread.is_alive()
        assert executed == []
        _button(dialog, "Approve Once").click()

    result, executed = _run_confirmation(qapp, controller, gui, approve)
    assert result == "closed"
    assert executed == [True]


def test_gui_scheduling_delay_does_not_consume_user_response_time(
    qapp, confirmation_env,
):
    controller, gui = confirmation_env
    gui.confirmation_timeout_ms = 100
    executed = []
    result = []
    intent = {"skill": "app.close", "params": {"target": "__all__"}}
    thread = threading.Thread(
        target=lambda: result.append(
            controller.action_manager.execute_intent(
                intent, lambda: executed.append(True) or "closed",
            )
        ),
        daemon=True,
    )
    thread.start()

    # Simulate a briefly busy Qt event loop for longer than the human response
    # timeout.  The action must remain pending until its dialog is presented.
    time.sleep(0.2)
    assert thread.is_alive()
    def approve_when_visible():
        dialog = gui._confirmation_dialog
        if dialog is not None and dialog.isVisible():
            _button(dialog, "Approve Once").click()
        elif thread.is_alive():
            QTimer.singleShot(5, approve_when_visible)

    QTimer.singleShot(0, approve_when_visible)
    deadline = time.time() + 1.0
    while thread.is_alive() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    thread.join(timeout=1.0)

    assert result == ["closed"]
    assert executed == [True]


def test_visible_dialog_timeout_is_owned_by_gui_timer(qapp, confirmation_env):
    controller, gui = confirmation_env
    gui.confirmation_timeout_ms = 50
    observed = []

    def briefly_block_gui(dialog, thread, _executed):
        assert dialog.isVisible()
        time.sleep(0.15)
        observed.append(thread.is_alive())

    result, executed = _run_confirmation(
        qapp, controller, gui, briefly_block_gui,
    )

    assert observed == [True]
    assert result == "Action denied because confirmation timed out."
    assert executed == []


def test_concurrent_confirmations_receive_independent_decisions(
    qapp, confirmation_env,
):
    controller, gui = confirmation_env
    executed = []
    results = {}

    def run(name):
        intent = {"skill": "app.close", "params": {"target": "__all__"}}
        results[name] = controller.action_manager.execute_intent(
            intent, lambda: executed.append(name) or f"{name} closed",
        )

    first = threading.Thread(target=run, args=("first",), daemon=True)
    second = threading.Thread(target=run, args=("second",), daemon=True)
    first.start()
    deadline = time.time() + 1.0
    while not gui.confirmation_pending() and time.time() < deadline:
        time.sleep(0.005)
    assert gui.confirmation_pending()
    second.start()
    dialogs = []

    def deny_second_when_visible():
        dialog = gui._confirmation_dialog
        if (
            dialog is not None
            and dialogs
            and dialog is not dialogs[0]
            and dialog.isVisible()
        ):
            dialogs.append(dialog)
            _button(dialog, "Deny").click()
        elif second.is_alive():
            QTimer.singleShot(5, deny_second_when_visible)

    def approve_first_when_visible():
        dialog = gui._confirmation_dialog
        if dialog is not None and dialog.isVisible():
            dialogs.append(dialog)
            _button(dialog, "Approve Once").click()
            QTimer.singleShot(0, deny_second_when_visible)
        elif first.is_alive():
            QTimer.singleShot(5, approve_first_when_visible)

    QTimer.singleShot(0, approve_first_when_visible)
    deadline = time.time() + 3.0
    while (first.is_alive() or second.is_alive()) and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    first.join(timeout=0.2)
    second.join(timeout=0.2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(dialogs) == 2
    assert results["first"] == "first closed"
    assert results["second"] == "Action denied by user."
    assert executed == ["first"]


def test_shutdown_cancels_active_and_queued_confirmations(
    qapp, confirmation_env,
):
    controller, gui = confirmation_env
    executed = []
    results = []
    intent = {"skill": "app.close", "params": {"target": "__all__"}}

    def run(name):
        results.append(controller.action_manager.execute_intent(
            intent, lambda: executed.append(name) or "unexpected execution",
        ))

    first = threading.Thread(target=run, args=("first",), daemon=True)
    second = threading.Thread(target=run, args=("second",), daemon=True)
    first.start()
    deadline = time.time() + 1.0
    while not gui.confirmation_pending() and time.time() < deadline:
        time.sleep(0.005)
    assert gui.confirmation_pending()
    second.start()

    gui.shutdown()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert executed == []
    assert sorted(results) == [
        "Task cancelled by user.",
        "Task cancelled by user.",
    ]


def test_deny_keeps_action_from_running(qapp, confirmation_env):
    controller, gui = confirmation_env
    result, executed = _run_confirmation(
        qapp, controller, gui,
        lambda dialog, _thread, _executed: _button(dialog, "Deny").click(),
    )
    assert result == "Action denied by user."
    assert executed == []


def test_cancel_task_keeps_action_from_running(qapp, confirmation_env, monkeypatch):
    controller, gui = confirmation_env
    stopped = []
    monkeypatch.setattr(controller, "stop_task", lambda: stopped.append(True) or True)
    result, executed = _run_confirmation(
        qapp, controller, gui,
        lambda dialog, _thread, _executed: _button(dialog, "Cancel Task").click(),
    )
    assert result == "Task cancelled by user."
    assert executed == []
    assert stopped == [True]


def test_confirmation_timeout_is_safe(qapp, confirmation_env):
    controller, gui = confirmation_env
    gui.confirmation_timeout_ms = 30
    result, executed = _run_confirmation(qapp, controller, gui)
    assert "timed out" in result
    assert executed == []


def test_dialog_close_counts_as_denial(qapp, confirmation_env):
    controller, gui = confirmation_env
    result, executed = _run_confirmation(
        qapp, controller, gui,
        lambda dialog, _thread, _executed: dialog.close(),
    )
    assert result == "Action denied by user."
    assert executed == []


@pytest.mark.parametrize(
    "transcript, expected, did_execute",
    (("yes", "closed", True), ("no", "Action denied by user.", False)),
)
def test_voice_confirmation_yes_and_no(
    qapp, confirmation_env, transcript, expected, did_execute
):
    controller, gui = confirmation_env
    engine = VoiceEngine(controller, controller.state, controller.speech)
    engine._listener = type(
        "Transcriber", (), {"transcribe": lambda self, _audio: transcript}
    )()

    def voice_decision(dialog, _thread, _executed):
        assert dialog is not None and dialog.isVisible()
        engine._do_transcription_and_route(object())

    result, executed = _run_confirmation(qapp, controller, gui, voice_decision)
    assert result == expected
    assert bool(executed) is did_execute


def test_voice_cancel_cancels_task(qapp, confirmation_env, monkeypatch):
    controller, gui = confirmation_env
    stopped = []
    monkeypatch.setattr(controller, "stop_task", lambda: stopped.append(True) or True)
    engine = VoiceEngine(controller, controller.state, controller.speech)
    engine._listener = type(
        "Transcriber", (), {"transcribe": lambda self, _audio: "cancel"}
    )()

    result, executed = _run_confirmation(
        qapp, controller, gui,
        lambda _dialog, _thread, _executed: engine._do_transcription_and_route(object()),
    )
    assert result == "Task cancelled by user."
    assert executed == []
    assert stopped == [True]


def test_sensitive_values_are_redacted_in_dialog(qapp, confirmation_env):
    controller, gui = confirmation_env
    action = Action(
        action_id="redaction",
        skill="windows",
        operation="close_all_jarvis_items",
        parameters={
            "target": str(os.path.expanduser("~")) + r"\Private",
            "password": "never-show-this",
            "body": "private message body",
        },
        permission_scope="DESKTOP_CONTROL",
        risk_level="high",
        requires_confirmation=True,
        reversible=True,
        rollback_action=None,
    )
    result = []
    thread = threading.Thread(
        target=lambda: result.append(gui._confirmation_handler_from_agent(action)),
        daemon=True,
    )

    def inspect_and_deny():
        dialog = gui._confirmation_dialog
        labels = " ".join(label.text() for label in dialog.findChildren(QLabel))
        assert "never-show-this" not in labels
        assert "private message body" not in labels
        assert str(os.path.expanduser("~")) not in labels
        assert "[REDACTED]" in labels
        assert "%USERPROFILE%" in labels
        _button(dialog, "Deny").click()

    thread.start()
    def inspect_when_visible():
        if gui._confirmation_dialog is not None and gui._confirmation_dialog.isVisible():
            inspect_and_deny()
        elif thread.is_alive():
            QTimer.singleShot(5, inspect_when_visible)

    QTimer.singleShot(0, inspect_when_visible)
    while thread.is_alive():
        qapp.processEvents()
        time.sleep(0.005)
    assert result == ["deny"]


def test_confirmation_request_and_result_are_audited(qapp, confirmation_env):
    controller, gui = confirmation_env
    _run_confirmation(
        qapp, controller, gui,
        lambda dialog, _thread, _executed: _button(dialog, "Deny").click(),
    )
    entries = [
        json.loads(line) for line in Config.AUDIT_LOG_FILE.read_text(encoding="utf-8").splitlines()
    ]
    outcomes = [entry["outcome"] for entry in entries]
    assert "confirmation_requested" in outcomes
    assert "denied" in outcomes


def test_action_schema_requires_every_field():
    payload = {
        "action_id": "schema-test",
        "skill": "windows",
        "operation": "open_folder",
        "parameters": {"folder": "Downloads"},
    }
    with pytest.raises(ValueError, match="Missing action fields"):
        Action.from_dict(payload)


def test_unknown_operation_is_rejected(confirmation_env):
    controller, _gui = confirmation_env
    action = Action(
        action_id="unknown-operation",
        skill="windows",
        operation="arbitrary_shell",
        parameters={},
        permission_scope="ADMINISTRATOR",
        risk_level="critical",
        requires_confirmation=False,
        reversible=False,
        rollback_action=None,
    )
    with pytest.raises(ValueError, match="Unknown operation"):
        controller.action_manager.execute_action(action)


def test_all_planner_and_router_actions_have_permission_scopes():
    assert ActionManager.INTENT_ALLOWLIST
    assert all(
        scope in Config.PERMISSION_SCOPES
        for scope, _risk in ActionManager.INTENT_ALLOWLIST.values()
    )
