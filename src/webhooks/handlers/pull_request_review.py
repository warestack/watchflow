from functools import lru_cache

import structlog

from src.core.models import WebhookEvent, WebhookResponse
from src.event_processors.pull_request.processor import PullRequestProcessor
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler

logger = structlog.get_logger()


@lru_cache(maxsize=1)
def get_pr_processor() -> PullRequestProcessor:
    return PullRequestProcessor()


class PullRequestReviewEventHandler(EventHandler):
    """Handler for pull_request_review events."""

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type.name == "PULL_REQUEST_REVIEW"

    async def handle(self, event: WebhookEvent) -> WebhookResponse:
        """
        Orchestrates pull_request_review processing.
        Re-evaluates PR rules when reviews are submitted or dismissed.
        """
        action = event.payload.get("action")
        log = logger.bind(
            event_type="pull_request_review",
            repo=event.repo_full_name,
            pr_number=event.payload.get("pull_request", {}).get("number"),
            action=action,
        )

        if action not in ("submitted", "dismissed"):
            log.info("ignoring_review_action")
            return WebhookResponse(status="ignored", detail=f"Action {action} ignored")

        log.info("pr_review_handler_invoked")

        try:
            processor = get_pr_processor()
            enqueued = await task_queue.enqueue(
                processor.process,
                "pull_request",
                event.payload,
                event,
                delivery_id=event.delivery_id,
            )

            if enqueued:
                return WebhookResponse(status="ok", detail="Pull request review event enqueued")
            else:
                return WebhookResponse(status="ignored", detail="Duplicate event skipped")

        except Exception as e:
            log.error("pr_review_handler_error", error=str(e))
            return WebhookResponse(status="error", detail=str(e))
