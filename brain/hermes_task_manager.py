"""Bounded, cancellable state records for optional Hermes-planned tasks."""
from __future__ import annotations

import dataclasses
import threading
import time
import uuid

from config import Config

TASK_STATUSES = frozenset({"QUEUED", "PLANNING", "WAITING_CONFIRMATION", "RUNNING", "PAUSED",
                           "RETRYING", "ROLLING_BACK", "COMPLETED", "FAILED", "CANCELLED"})


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

    def create(self, goal: str, owner="user") -> HermesTask:
        with self._lock:
            active = sum(t.status in {"QUEUED", "PLANNING", "WAITING_CONFIRMATION", "RUNNING", "PAUSED", "RETRYING"}
                         for t in self._tasks.values())
            if active >= self.max_concurrent:
                raise RuntimeError("Hermes task concurrency limit reached")
            task = HermesTask(task_id=str(uuid.uuid4()), goal=str(goal), owner=owner)
            self._tasks[task.task_id] = task
            return dataclasses.replace(task)

    def get(self, task_id: str) -> HermesTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return dataclasses.replace(task) if task else None

    def list(self) -> list[HermesTask]:
        with self._lock:
            return [dataclasses.replace(task) for task in self._tasks.values()]

    def transition(self, task_id: str, status: str, *, error="", steps=None) -> HermesTask:
        if status not in TASK_STATUSES:
            raise ValueError("unknown Hermes task status")
        with self._lock:
            task = self._tasks[task_id]
            if task.cancellation_token and status not in {"CANCELLED", "FAILED"}:
                raise RuntimeError("task is cancelled")
            task.status, task.updated_at = status, time.time()
            if status == "RUNNING" and task.started_at is None:
                task.started_at = task.updated_at
            if status in {"COMPLETED", "FAILED", "CANCELLED"}:
                task.completed_at = task.updated_at
            if error:
                task.last_error = str(error)
            if steps is not None:
                task.total_steps = int(steps)
            return dataclasses.replace(task)

    def pause(self, task_id): return self.transition(task_id, "PAUSED")
    def resume(self, task_id): return self.transition(task_id, "RUNNING")

    def cancel(self, task_id: str) -> HermesTask:
        with self._lock:
            task = self._tasks[task_id]
            task.cancellation_token = True
        return self.transition(task_id, "CANCELLED")

    def cancel_all(self) -> int:
        with self._lock:
            ids = [task.task_id for task in self._tasks.values()
                   if task.status not in {"COMPLETED", "FAILED", "CANCELLED"}]
        for task_id in ids:
            self.cancel(task_id)
        return len(ids)
