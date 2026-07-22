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
