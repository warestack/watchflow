import asyncio
import hashlib
import json
from collections.abc import Callable, Coroutine
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class Task(BaseModel):
    """Strictly typed task container for the queue."""

    task_id: str = Field(..., description="Unique hash for deduplication")
    event_type: str = Field(..., description="GitHub event type")
    payload: dict[str, Any] = Field(..., description="Event payload for hash generation")
    func: Callable[..., Coroutine[Any, Any, Any]] | Any = Field(..., description="Handler function to execute")
    args: tuple[Any, ...] = Field(default_factory=tuple, description="Positional arguments")
    kwargs: dict[str, Any] = Field(default_factory=dict, description="Keyword arguments")

    model_config = {"arbitrary_types_allowed": True}


class TaskQueue:
    """
    In-memory task queue with deduplication as per Blueprint 2.3.C.
    Prevents processing the same GitHub event multiple times.
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[Task] = asyncio.Queue()
        self.processed_hashes: set[str] = set()
        self.workers: list[asyncio.Task[None]] = []

    def _generate_task_id(self, event_type: str, payload: dict[str, Any]) -> str:
        """Creates a unique hash for deduplication."""
        payload_str = json.dumps(payload, sort_keys=True)
        raw_string = f"{event_type}:{payload_str}"
        return hashlib.sha256(raw_string.encode()).hexdigest()

    async def enqueue(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        event_type: str,
        payload: dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """Adds a task to the queue if it is not a duplicate."""
        task_id = self._generate_task_id(event_type, payload)

        if task_id in self.processed_hashes:
            logger.info("task_skipped_duplicate", task_id=task_id, event_type=event_type)
            return False

        task = Task(task_id=task_id, event_type=event_type, payload=payload, func=func, args=args, kwargs=kwargs)
        await self.queue.put(task)
        self.processed_hashes.add(task_id)

        logger.info("task_enqueued", task_id=task_id, event_type=event_type)
        return True

    async def _worker(self) -> None:
        """Background worker loop."""
        while True:
            task = await self.queue.get()
            try:
                logger.info("task_started", task_id=task.task_id, event_type=task.event_type)
                await task.func(*task.args, **task.kwargs)
                logger.info("task_completed", task_id=task.task_id)
            except Exception as e:
                logger.error("task_failed", task_id=task.task_id, error=str(e), exc_info=True)
            finally:
                self.queue.task_done()

    async def start_workers(self, num_workers: int = 1) -> None:
        """Starts the background workers."""
        if not self.workers:
            for _ in range(num_workers):
                task = asyncio.create_task(self._worker())
                self.workers.append(task)
            logger.info("task_queue_workers_started", count=num_workers)

    async def stop_workers(self) -> None:
        """Stops the background workers."""
        if self.workers:
            for task in self.workers:
                task.cancel()
            await asyncio.gather(*self.workers, return_exceptions=True)
            self.workers.clear()
            logger.info("task_queue_workers_stopped")


# Global singleton for the application
task_queue = TaskQueue()
