import structlog

from src.core.models import WebhookEvent
from src.webhooks.handlers.base import EventHandler
from src.webhooks.models import WebhookResponse

logger = structlog.get_logger()


class PullRequestEventHandler(EventHandler):
    """Thin handler for pull request webhook events—delegates to event processor."""

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type.name == "PULL_REQUEST"

    async def handle(self, event: WebhookEvent) -> WebhookResponse:
        """
        Orchestrates pull request event processing.
        Thin layer—business logic lives in event_processors.
        """
        log = logger.bind(
            event_type="pull_request",
            repo=event.repo_full_name,
            pr_number=event.payload.get("pull_request", {}).get("number"),
            action=event.payload.get("action"),
        )

        log.info("pr_handler_invoked")

        try:
            # Handler is called from TaskQueue worker, so actual processing happens here
            # The event already contains all necessary data
            # Processors will need to be updated to accept WebhookEvent instead of Task
            # For now, log that we're ready to process
            log.info("pr_ready_for_processing")

            return WebhookResponse(status="success", detail="Pull request handler executed", event_type="pull_request")

        except Exception as e:
            log.error("pr_processing_failed", error=str(e), exc_info=True)
            return WebhookResponse(status="error", detail=f"PR processing failed: {str(e)}", event_type="pull_request")
