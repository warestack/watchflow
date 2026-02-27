from typing import Any

import structlog

from src.core.models import WebhookEvent
from src.event_processors.pull_request.processor import handle_pull_request

logger = structlog.get_logger()

async def handle_pull_request_review(event_type: str, payload: dict[str, Any], event: WebhookEvent) -> dict[str, Any]:
    """
    Handle pull_request_review events.
    When a review is submitted, we want to re-evaluate the PR rules because:
    1. A missing approval might now be present
    2. A required code owner might have reviewed
    """
    # Verify this is a submitted review or a dismissed review
    action = payload.get("action")
    if action not in ("submitted", "dismissed"):
        logger.info(f"Ignoring pull_request_review action: {action}")
        return {"status": "skipped", "reason": f"Action {action} ignored"}

    # We just delegate to the main pull request processor to re-run the engine
    # since a review can change the pass/fail state of PR conditions
    return await handle_pull_request(event_type, payload, event)
