import structlog

from src.core.models import EventType, WebhookEvent, WebhookResponse
from src.event_processors.check_run import CheckRunProcessor
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler

logger = structlog.get_logger(__name__)

# Instantiate processor once (same pattern as push_processor)
check_run_processor = CheckRunProcessor()


class CheckRunEventHandler(EventHandler):
    """Handler for check run webhook events using task queue."""

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type == EventType.CHECK_RUN

    async def handle(self, event: WebhookEvent) -> WebhookResponse:
        """Handle check run events by enqueuing them for background processing."""
        logger.info(
            "Enqueuing check run event",
            operation="enqueue_check_run",
            subject_ids=[event.repo_full_name],
            decision="pending",
            latency_ms=0,
            repo=event.repo_full_name,
        )

        task = task_queue.build_task(
            "check_run",
            event.payload,
            check_run_processor.process,
            delivery_id=event.delivery_id,
        )
        enqueued = await task_queue.enqueue(
            check_run_processor.process,
            "check_run",
            event.payload,
            task,
            delivery_id=event.delivery_id,
        )

        if enqueued:
            logger.info(
                "Check run event enqueued",
                operation="enqueue_check_run",
                subject_ids=[event.repo_full_name],
                decision="enqueued",
                latency_ms=0,
            )
            return WebhookResponse(
                status="ok",
                detail="Check run event has been queued for processing",
                event_type=EventType.CHECK_RUN,
            )
        logger.info(
            "Check run event duplicate skipped",
            operation="enqueue_check_run",
            subject_ids=[event.repo_full_name],
            decision="duplicate_skipped",
            latency_ms=0,
        )
        return WebhookResponse(
            status="ignored",
            detail="Duplicate check run event skipped",
            event_type=EventType.CHECK_RUN,
        )
