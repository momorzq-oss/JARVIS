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
