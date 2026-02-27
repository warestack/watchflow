from typing import Any

import structlog

from src.core.models import WebhookEvent
from src.event_processors.pull_request.processor import handle_pull_request

logger = structlog.get_logger()


async def handle_pull_request_review_thread(
    event_type: str, payload: dict[str, Any], event: WebhookEvent
) -> dict[str, Any]:
    """
    Handle pull_request_review_thread events.
    When a thread is resolved or unresolved, we want to re-evaluate the PR rules because:
    1. UnresolvedCommentsCondition depends on thread resolution status
    """
    # Verify this is a resolved or unresolved action
    action = payload.get("action")
    if action not in ("resolved", "unresolved"):
        logger.info(f"Ignoring pull_request_review_thread action: {action}")
        return {"status": "skipped", "reason": f"Action {action} ignored"}

    # We just delegate to the main pull request processor to re-run the engine
    # since a thread resolution can change the pass/fail state of PR conditions
    return await handle_pull_request(event_type, payload, event)
