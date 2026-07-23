"""Bounded, cancellable state records for optional Hermes-planned tasks."""
from __future__ import annotations

import dataclasses
import threading
import time
import uuid

from config import Config

TASK_STATUSES = frozenset({"QUEUED", "PLANNING", "WAITING_CONFIRMATION", "RUNNING", "PAUSED",
                           "RETRYING", "ROLLING_BACK", "COMPLETED", "FAILED", "CANCELLED"})
TERMINAL_TASK_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
TASK_TRANSITIONS = {
    "QUEUED": frozenset({"PLANNING", "WAITING_CONFIRMATION", "RUNNING", "FAILED", "CANCELLED"}),
    "PLANNING": frozenset({"WAITING_CONFIRMATION", "FAILED", "CANCELLED"}),
    "WAITING_CONFIRMATION": frozenset({"RUNNING", "FAILED", "CANCELLED"}),
    "RUNNING": frozenset({"PAUSED", "RETRYING", "ROLLING_BACK", "COMPLETED", "FAILED", "CANCELLED"}),
    "PAUSED": frozenset({"RUNNING", "ROLLING_BACK", "FAILED", "CANCELLED"}),
    "RETRYING": frozenset({"RUNNING", "PAUSED", "ROLLING_BACK", "FAILED", "CANCELLED"}),
    "ROLLING_BACK": frozenset({"COMPLETED", "FAILED", "CANCELLED"}),
    "COMPLETED": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
}


@dataclasses.dataclass
class HermesTask:
    task_id: str
    goal: str
    status: str = "QUEUED"
    created_at: float = dataclasses.field(default_factory=time.time)
    started_at: float | None = None
    updated_at: float = dataclasses.field(default_factory=time.time)
    completed_at: float | None = None
    current_step: int = 0
    total_steps: int = 0
    progress: float = 0.0
    capabilities_used: list[str] = dataclasses.field(default_factory=list)
    permissions: list[str] = dataclasses.field(default_factory=list)
    confirmations: list[str] = dataclasses.field(default_factory=list)
    output_files: list[str] = dataclasses.field(default_factory=list)
    last_error: str = ""
    retries: int = 0
    cancellation_token: bool = False
    owner: str = "user"


class HermesTaskManager:
    def __init__(self, max_concurrent=None):
        self.max_concurrent = Config.HERMES_MAX_CONCURRENT_TASKS if max_concurrent is None else int(max_concurrent)
        self._tasks: dict[str, HermesTask] = {}
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)

    @staticmethod
    def _snapshot(task: HermesTask) -> HermesTask:
        """Return a detached task value safe for callers to mutate."""
        return dataclasses.replace(
            task,
            capabilities_used=list(task.capabilities_used),
            permissions=list(task.permissions),
            confirmations=list(task.confirmations),
            output_files=list(task.output_files),
        )

    def create(self, goal: str, owner="user") -> HermesTask:
        with self._lock:
            active = sum(t.status in {"QUEUED", "PLANNING", "WAITING_CONFIRMATION", "RUNNING", "PAUSED", "RETRYING"}
                         for t in self._tasks.values())
            if active >= self.max_concurrent:
                raise RuntimeError("Hermes task concurrency limit reached")
            task = HermesTask(task_id=str(uuid.uuid4()), goal=str(goal), owner=owner)
            self._tasks[task.task_id] = task
            self._changed.notify_all()
            return self._snapshot(task)

    def get(self, task_id: str) -> HermesTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return self._snapshot(task) if task else None

    def list(self) -> list[HermesTask]:
        with self._lock:
            return [self._snapshot(task) for task in self._tasks.values()]

    def transition(self, task_id: str, status: str, *, error="", steps=None) -> HermesTask:
        if status not in TASK_STATUSES:
            raise ValueError("unknown Hermes task status")
        with self._lock:
            task = self._tasks[task_id]
            if status != task.status and status not in TASK_TRANSITIONS[task.status]:
                raise RuntimeError(
                    f"invalid Hermes task transition: {task.status} -> {status}"
                )
            if task.cancellation_token and status != "CANCELLED":
                raise RuntimeError("task is cancelled")
            task.status, task.updated_at = status, time.time()
            if status == "RUNNING" and task.started_at is None:
                task.started_at = task.updated_at
            if status in TERMINAL_TASK_STATUSES:
                task.completed_at = task.updated_at
            if error:
                task.last_error = str(error)
            if steps is not None:
                task.total_steps = int(steps)
            self._changed.notify_all()
            return self._snapshot(task)

    def pause(self, task_id): return self.transition(task_id, "PAUSED")
    def resume(self, task_id): return self.transition(task_id, "RUNNING")

    def cancel(self, task_id: str) -> HermesTask:
        with self._lock:
            task = self._tasks[task_id]
            if task.status == "CANCELLED":
                return self._snapshot(task)
            if task.status in TERMINAL_TASK_STATUSES:
                raise RuntimeError(f"task is already {task.status.lower()}")
            task.cancellation_token = True
            # RLock keeps token and terminal state publication atomic while
            # transition applies the normal timestamps and notifications.
            return self.transition(task_id, "CANCELLED")

    def record_confirmation(self, task_id: str, decision: str) -> HermesTask:
        with self._lock:
            task = self._tasks[task_id]
            task.confirmations.append(str(decision))
            task.updated_at = time.time()
            self._changed.notify_all()
            return self._snapshot(task)

    def record_retry(self, task_id: str, error: str) -> HermesTask:
        with self._lock:
            task = self._tasks[task_id]
            task.retries += 1
            task.last_error = str(error)
            task.updated_at = time.time()
            self._changed.notify_all()
            return self._snapshot(task)

    def complete_step(self, task_id: str, capability_id: str, permission: str,
                      output_files=None) -> HermesTask:
        with self._lock:
            task = self._tasks[task_id]
            if task.cancellation_token:
                raise RuntimeError("task is cancelled")
            task.current_step = min(task.total_steps, task.current_step + 1)
            task.progress = (
                task.current_step / task.total_steps if task.total_steps else 1.0
            )
            if capability_id not in task.capabilities_used:
                task.capabilities_used.append(str(capability_id))
            if permission not in task.permissions:
                task.permissions.append(str(permission))
            for path in output_files or ():
                value = str(path)
                if value and value not in task.output_files:
                    task.output_files.append(value)
            task.updated_at = time.time()
            self._changed.notify_all()
            return self._snapshot(task)

    def wait_until_runnable(self, task_id: str, timeout=None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0, float(timeout))
        with self._changed:
            while True:
                task = self._tasks[task_id]
                if task.cancellation_token or task.status == "CANCELLED":
                    return False
                if task.status != "PAUSED":
                    return True
                if deadline is None:
                    self._changed.wait(0.1)
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._changed.wait(min(0.1, remaining))

    def cancel_all(self) -> int:
        with self._lock:
            ids = [task.task_id for task in self._tasks.values()
                   if task.status not in {"COMPLETED", "FAILED", "CANCELLED"}]
        for task_id in ids:
            self.cancel(task_id)
        return len(ids)
