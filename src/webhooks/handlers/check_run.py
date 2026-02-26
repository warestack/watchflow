import structlog

from src.core.models import WebhookEvent
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler

logger = structlog.get_logger()


class CheckRunEventHandler(EventHandler):
    """Handler for check run webhook events using task queue."""

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type.name == "CHECK_RUN"

    async def handle(self, event: WebhookEvent):
        """Handle check run events by enqueuing them for background processing."""
        logger.info("enqueuing_check_run_event_for", repo_full_name=event.repo_full_name)

        task_id = await task_queue.enqueue(
            event_type="check_run",
            repo_full_name=event.repo_full_name,
            installation_id=event.installation_id,
            payload=event.payload,
        )

        logger.info("check_run_event_enqueued_with_task", task_id=task_id)

        return {"status": "enqueued", "task_id": task_id, "message": "Check run event has been queued for processing"}
