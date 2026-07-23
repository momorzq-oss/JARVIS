import pytest

from brain.hermes_task_manager import HermesTaskManager


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
