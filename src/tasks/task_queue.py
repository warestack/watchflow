import asyncio
import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Task(BaseModel):
    """Represents a task in the processing queue."""

    id: str
    event_type: str
    repo_full_name: str
    installation_id: int
    payload: dict[str, Any]
    status: TaskStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    event_hash: str | None = None  # For deduplication


class TaskQueue:
    """Simple in-memory task queue for background processing with deduplication."""

    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.event_hashes: dict[str, str] = {}  # event_hash -> task_id
        self.running = False
        self.workers = []

    def _create_event_hash(self, event_type: str, repo_full_name: str, payload: dict[str, Any]) -> str:
        """Create a unique hash for the event to enable deduplication."""
        # Create a stable identifier based on event type, repo, and key payload fields
        event_data = {
            "event_type": event_type,
            "repo_full_name": repo_full_name,
            "action": payload.get("action"),
            "sender": payload.get("sender", {}).get("login"),
        }

        # Add event-specific identifiers
        if event_type == "pull_request":
            pr_data = payload.get("pull_request", {})
            event_data.update(
                {
                    "pr_number": pr_data.get("number"),
                    "pr_title": pr_data.get("title"),
                    "pr_state": pr_data.get("state"),
                    "pr_body": pr_data.get("body"),  # Include body for description changes
                    "pr_updated_at": pr_data.get("updated_at"),  # Include update timestamp
                }
            )
        elif event_type == "push":
            head_commit = payload.get("head_commit")
            event_data.update(
                {
                    "ref": payload.get("ref"),
                    "head_commit": head_commit.get("id") if head_commit else None,
                }
            )
        elif event_type == "check_run":
            check_run = payload.get("check_run", {})
            event_data.update(
                {
                    "check_run_id": check_run.get("id"),
                    "check_run_name": check_run.get("name"),
                    "check_run_status": check_run.get("status"),
                }
            )
        elif event_type == "issue_comment":
            # For issue comments (including acknowledgments), include the comment content
            # to allow multiple acknowledgments with different reasons
            comment = payload.get("comment", {})
            event_data.update(
                {
                    "issue_number": payload.get("issue", {}).get("number"),
                    "comment_id": comment.get("id"),
                    "comment_body": comment.get("body"),  # Include comment body to differentiate acknowledgments
                    "comment_created_at": comment.get("created_at"),
                }
            )

        # Create hash from the event data
        event_json = json.dumps(event_data, sort_keys=True)
        event_hash = hashlib.md5(event_json.encode()).hexdigest()

        # Debug logging for issue_comment events
        if event_type == "issue_comment":
            logger.info(f"🔍 Event hash debug for {event_type}:")
            logger.info(f"    Comment ID: {event_data.get('comment_id')}")
            logger.info(f"    Comment body: {event_data.get('comment_body', '')[:50]}...")
            logger.info(f"    Comment created at: {event_data.get('comment_created_at')}")
            logger.info(f"    Event hash: {event_hash}")

        return event_hash

    async def enqueue(self, event_type: str, repo_full_name: str, installation_id: int, payload: dict[str, Any]) -> str:
        """Enqueue a new task for background processing."""
        task_id = f"{event_type}_{repo_full_name}_{datetime.now().timestamp()}"

        task = Task(
            id=task_id,
            event_type=event_type,
            repo_full_name=repo_full_name,
            installation_id=installation_id,
            payload=payload,
            status=TaskStatus.PENDING,
            created_at=datetime.now(),
            event_hash=None,  # No deduplication for now
        )

        self.tasks[task_id] = task

        logger.info(f"Enqueued task {task_id} for {repo_full_name}")

        return task_id

    async def start_workers(self, num_workers: int = 3):
        """Start background workers."""
        self.running = True
        for i in range(num_workers):
            worker = asyncio.create_task(self._worker(f"worker-{i}"))
            self.workers.append(worker)
        logger.info(f"Started {num_workers} background workers")

    async def stop_workers(self):
        """Stop background workers."""
        self.running = False
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        logger.info("Stopped all background workers")

    async def _worker(self, worker_name: str):
        """Background worker that processes tasks."""
        logger.info(f"Worker {worker_name} started")

        last_cleanup = datetime.now()
        cleanup_interval = 3600  # Clean up every hour

        while self.running:
            try:
                # Periodic cleanup
                if (datetime.now() - last_cleanup).total_seconds() > cleanup_interval:
                    self.cleanup_old_tasks()
                    last_cleanup = datetime.now()

                # Find pending tasks
                pending_tasks = [task for task in self.tasks.values() if task.status == TaskStatus.PENDING]

                if pending_tasks:
                    # Process the oldest task
                    task = min(pending_tasks, key=lambda t: t.created_at)
                    await self._process_task(task, worker_name)
                else:
                    # No tasks, wait a bit
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Worker {worker_name} error: {e}")
                await asyncio.sleep(5)

        logger.info(f"Worker {worker_name} stopped")

    async def _process_task(self, task: Task, worker_name: str):
        """Process a single task."""
        try:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()

            logger.info(f"Worker {worker_name} processing task {task.id}")

            # Get the appropriate processor
            processor = self._get_processor(task.event_type)
            result = await processor.process(task)

            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            task.result = result.__dict__ if hasattr(result, "__dict__") else result

            logger.info(f"Task {task.id} completed successfully")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now()
            task.error = str(e)
            logger.error(f"Task {task.id} failed: {e}")

    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """Clean up old completed tasks and their event hashes to prevent memory leaks."""
        cutoff_time = datetime.now().timestamp() - (max_age_hours * 3600)

        # Find old completed tasks
        old_task_ids = [
            task_id
            for task_id, task in self.tasks.items()
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED] and task.created_at.timestamp() < cutoff_time
        ]

        # Remove old tasks and their event hashes
        for task_id in old_task_ids:
            task = self.tasks[task_id]
            if task.event_hash and task.event_hash in self.event_hashes:
                del self.event_hashes[task.event_hash]
            del self.tasks[task_id]

        if old_task_ids:
            logger.info(f"Cleaned up {len(old_task_ids)} old tasks")

    def _get_processor(self, event_type: str):
        """Get the appropriate processor for the event type."""
        from src.event_processors.factory import EventProcessorFactory

        return EventProcessorFactory.create_processor(event_type)


# Global task queue instance
task_queue = TaskQueue()
