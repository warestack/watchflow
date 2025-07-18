import logging
from typing import Any

from src.core.models import WebhookEvent
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler

logger = logging.getLogger(__name__)


class PullRequestEventHandler(EventHandler):
    """Handler for pull request webhook events using task queue."""

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type.name == "PULL_REQUEST"

    async def handle(self, event: WebhookEvent) -> dict[str, Any]:
        """Handle pull request events by enqueuing them for background processing."""
        logger.info(f"🔄 Enqueuing pull request event for {event.repo_full_name}")

        task_id = await task_queue.enqueue(
            event_type="pull_request",
            repo_full_name=event.repo_full_name,
            installation_id=event.installation_id,
            payload=event.payload,
        )

        logger.info(f"✅ Pull request event enqueued with task ID: {task_id}")

        return {
            "status": "enqueued",
            "task_id": task_id,
            "message": "Pull request event has been queued for processing",
        }
