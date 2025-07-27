import logging

from src.core.models import WebhookEvent
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler

logger = logging.getLogger(__name__)


class StatusEventHandler(EventHandler):
    """Handler for status webhook events using task queue."""

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type.name == "STATUS"

    async def handle(self, event: WebhookEvent):
        """Handle status events by enqueuing them for background processing."""
        logger.info(f"🔄 Enqueuing status event for {event.repo_full_name}")

        task_id = await task_queue.enqueue(
            event_type="status",
            repo_full_name=event.repo_full_name,
            installation_id=event.installation_id,
            payload=event.payload,
        )

        logger.info(f"✅ Status event enqueued with task ID: {task_id}")

        return {"status": "enqueued", "task_id": task_id, "message": "Status event has been queued for processing"}
