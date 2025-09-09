import logging

from src.core.models import WebhookEvent
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler

logger = logging.getLogger(__name__)


class PushEventHandler(EventHandler):
    """Handler for push webhook events using task queue."""

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type.name == "PUSH"

    async def handle(self, event: WebhookEvent):
        """Handle push events by enqueuing them for background processing."""
        logger.info(f"🔄 Enqueuing push event for {event.repo_full_name}")

        task_id = await task_queue.enqueue(
            event_type="push",
            repo_full_name=event.repo_full_name,
            installation_id=event.installation_id,
            payload=event.payload,
        )

        logger.info(f"✅ Push event enqueued with task ID: {task_id}")

        return {"status": "enqueued", "task_id": task_id, "message": "Push event has been queued for processing"}
