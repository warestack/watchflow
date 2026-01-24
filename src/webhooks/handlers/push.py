import structlog

from src.core.models import WebhookEvent
from src.webhooks.handlers.base import EventHandler
from src.webhooks.models import WebhookResponse

logger = structlog.get_logger()


class PushEventHandler(EventHandler):
    """Thin handler for push webhook events—delegates to event processor."""

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type.name == "PUSH"

    async def handle(self, event: WebhookEvent) -> WebhookResponse:
        """
        Orchestrates push event processing.
        Thin layer—business logic lives in event_processors.
        """
        log = logger.bind(
            event_type="push",
            repo=event.repo_full_name,
            ref=event.payload.get("ref"),
            commits_count=len(event.payload.get("commits", [])),
        )

        log.info("push_handler_invoked")

        try:
            # Handler is thin—just logs and confirms readiness
            log.info("push_ready_for_processing")

            return WebhookResponse(status="success", detail="Push handler executed", event_type="push")

        except ImportError:
            # Deployment processor may not exist yet
            log.warning("deployment_processor_not_found")
            return WebhookResponse(status="success", detail="Push acknowledged (no processor)", event_type="push")
        except Exception as e:
            log.error("push_processing_failed", error=str(e), exc_info=True)
            return WebhookResponse(status="error", detail=f"Push processing failed: {str(e)}", event_type="push")
