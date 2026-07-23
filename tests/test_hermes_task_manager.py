import pytest

from brain.hermes_task_manager import HermesTaskManager
from config import Config


def test_task_lifecycle_pause_resume_cancel():
    manager = HermesTaskManager(max_concurrent=2)
    task = manager.create("research")
    manager.transition(task.task_id, "RUNNING", steps=2)
    assert manager.pause(task.task_id).status == "PAUSED"
    assert manager.resume(task.task_id).status == "RUNNING"
    assert manager.cancel(task.task_id).status == "CANCELLED"


def test_concurrency_limit():
    manager = HermesTaskManager(max_concurrent=1)
    manager.create("one")
    with pytest.raises(RuntimeError, match="limit"):
        manager.create("two")


def test_task_records_verified_step_progress_and_outputs():
    manager = HermesTaskManager(max_concurrent=1)
    task = manager.create("goal")
    manager.transition(task.task_id, "RUNNING", steps=2)

    current = manager.complete_step(
        task.task_id, "research.search_web", "BROWSER_NAVIGATE",
        ["result.json"],
    )

    assert current.current_step == 1
    assert current.progress == 0.5
    assert current.capabilities_used == ["research.search_web"]
    assert current.permissions == ["BROWSER_NAVIGATE"]
    assert current.output_files == ["result.json"]


def test_task_snapshots_do_not_expose_mutable_manager_state():
    manager = HermesTaskManager(max_concurrent=2)
    created = manager.create("Research safely")
    created.capabilities_used.append("unsafe.external.mutation")
    created.permissions.append("UNSAFE")
    created.confirmations.append("forged")
    created.output_files.append("outside.txt")

    stored = manager.get(created.task_id)
    assert stored is not None
    assert stored.capabilities_used == []
    assert stored.permissions == []
    assert stored.confirmations == []
    assert stored.output_files == []

    listed = manager.list()[0]
    listed.confirmations.append("also forged")
    assert manager.get(created.task_id).confirmations == []


def test_updated_task_snapshots_are_detached_from_internal_lists():
    manager = HermesTaskManager(max_concurrent=1)
    task = manager.create("Create a report")
    manager.transition(task.task_id, "RUNNING", steps=1)
    updated = manager.complete_step(
        task.task_id,
        "research.search_web",
        "NETWORK_PUBLIC_READ",
        ["result.json"],
    )
    updated.capabilities_used.clear()
    updated.permissions.clear()
    updated.output_files.clear()

    stored = manager.get(task.task_id)
    assert stored is not None
    assert stored.capabilities_used == ["research.search_web"]
    assert stored.permissions == ["NETWORK_PUBLIC_READ"]
    assert stored.output_files == ["result.json"]


@pytest.mark.parametrize("terminal", ["COMPLETED", "FAILED", "CANCELLED"])
def test_terminal_tasks_cannot_be_resurrected(terminal):
    manager = HermesTaskManager(max_concurrent=1)
    task = manager.create("terminal state")
    if terminal == "CANCELLED":
        manager.cancel(task.task_id)
    else:
        manager.transition(task.task_id, "RUNNING")
        manager.transition(task.task_id, terminal)

    with pytest.raises(RuntimeError, match="invalid Hermes task transition"):
        manager.transition(task.task_id, "RUNNING")
    assert manager.get(task.task_id).status == terminal


def test_task_manager_rejects_impossible_pause_and_planning_sequences():
    manager = HermesTaskManager(max_concurrent=2)
    queued = manager.create("queued")
    with pytest.raises(RuntimeError, match="QUEUED -> PAUSED"):
        manager.pause(queued.task_id)

    planning = manager.create("planning")
    manager.transition(planning.task_id, "PLANNING")
    with pytest.raises(RuntimeError, match="PLANNING -> COMPLETED"):
        manager.transition(planning.task_id, "COMPLETED")


def test_cancel_is_idempotent_and_late_failure_cannot_win():
    manager = HermesTaskManager(max_concurrent=1)
    task = manager.create("cancel safely")
    manager.transition(task.task_id, "RUNNING")

    cancelled = manager.cancel(task.task_id)
    assert manager.cancel(task.task_id).status == "CANCELLED"
    with pytest.raises(RuntimeError, match="invalid Hermes task transition"):
        manager.transition(task.task_id, "FAILED", error="late worker failure")

    stored = manager.get(task.task_id)
    assert stored.status == "CANCELLED"
    assert stored.completed_at == cancelled.completed_at
    assert stored.last_error == ""


@pytest.mark.parametrize("terminal", ["COMPLETED", "FAILED"])
def test_cancel_does_not_mutate_already_terminal_tasks(terminal):
    manager = HermesTaskManager(max_concurrent=1)
    task = manager.create("already terminal")
    manager.transition(task.task_id, "RUNNING")
    manager.transition(task.task_id, terminal)

    with pytest.raises(RuntimeError, match=f"already {terminal.lower()}"):
        manager.cancel(task.task_id)
    assert manager.get(task.task_id).cancellation_token is False


def test_task_record_updates_require_valid_execution_states(monkeypatch):
    manager = HermesTaskManager(max_concurrent=2)
    queued = manager.create("queued")
    with pytest.raises(RuntimeError, match="waiting for confirmation"):
        manager.record_confirmation(queued.task_id, "forged")
    with pytest.raises(RuntimeError, match="not running"):
        manager.record_retry(queued.task_id, "forged")
    with pytest.raises(RuntimeError, match="not executing"):
        manager.complete_step(queued.task_id, "browser.read_page", "SAFE_READ")

    running = manager.create("running")
    manager.transition(running.task_id, "RUNNING", steps=1)
    manager.complete_step(running.task_id, "browser.read_page", "SAFE_READ")
    with pytest.raises(RuntimeError, match="no remaining planned step"):
        manager.complete_step(running.task_id, "browser.read_page", "SAFE_READ")


def test_step_and_retry_limits_are_enforced(monkeypatch):
    manager = HermesTaskManager(max_concurrent=2)
    task = manager.create("bounded")
    with pytest.raises(ValueError, match="outside policy"):
        manager.transition(
            task.task_id, "WAITING_CONFIRMATION",
            steps=Config.HERMES_MAX_STEPS + 1,
        )

    retrying = manager.create("retrying")
    manager.transition(retrying.task_id, "RUNNING", steps=1)
    monkeypatch.setattr(Config, "HERMES_MAX_RETRIES", 1)
    manager.record_retry(retrying.task_id, "first")
    with pytest.raises(RuntimeError, match="retry limit"):
        manager.record_retry(retrying.task_id, "second")


def test_completed_task_clears_recovered_retry_error():
    manager = HermesTaskManager(max_concurrent=1)
    task = manager.create("recover")
    manager.transition(task.task_id, "RUNNING", steps=1)
    manager.record_retry(task.task_id, "temporary")
    manager.transition(task.task_id, "RETRYING", error="temporary")
    manager.transition(task.task_id, "RUNNING")
    manager.complete_step(task.task_id, "browser.read_page", "SAFE_READ")
    completed = manager.transition(task.task_id, "COMPLETED")
    assert completed.last_error == ""


def test_manager_timestamps_remain_strictly_ordered_on_coarse_clock(monkeypatch):
    monkeypatch.setattr("brain.hermes_task_manager.time.time", lambda: 100.0)
    manager = HermesTaskManager(max_concurrent=2)
    first = manager.create("first")
    second = manager.create("second")
    updated = manager.transition(first.task_id, "RUNNING", steps=1)

    assert first.created_at < second.created_at < updated.updated_at
