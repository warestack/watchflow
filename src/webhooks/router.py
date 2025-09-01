import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from src.core.models import EventType, WebhookEvent
from src.webhooks.auth import verify_github_signature
from src.webhooks.dispatcher import WebhookDispatcher, dispatcher

logger = logging.getLogger(__name__)
router = APIRouter()


# Dependency provider for the dispatcher instance.
# This makes it easy to manage its lifecycle and use it in tests.
def get_dispatcher() -> WebhookDispatcher:
    """Returns the shared WebhookDispatcher instance."""
    return dispatcher


def _create_event_from_request(event_name: str | None, payload: dict) -> WebhookEvent:
    """Factory function to create a WebhookEvent from raw request data."""
    if not event_name:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

    # Normalize event name for events like deployment_review.requested
    normalized_event_name = event_name.split(".")[0]
    logger.info(f"Received event: {event_name}, normalized: {normalized_event_name}")

    try:
        # Map the string from the header (e.g., "pull_request") to our enum
        event_type = EventType(normalized_event_name)
    except ValueError as e:
        logger.warning(f"Received an unsupported event type: {event_name} - {e}")
        # If the event isn't in our enum, we can't process it.
        # We'll return a success response to GitHub to acknowledge receipt
        # but won't do any work.
        raise HTTPException(status_code=202, detail=f"Event type '{event_name}' is received but not supported.") from e

    return WebhookEvent(event_type=event_type, payload=payload)


@router.post("/github", summary="Endpoint for all GitHub webhooks")
async def github_webhook_endpoint(
    request: Request,
    is_verified: bool = Depends(verify_github_signature),
    dispatcher_instance: WebhookDispatcher = Depends(get_dispatcher),
):
    """
    This endpoint receives all events from a configured GitHub App.

    - It first verifies the request signature to ensure it's from GitHub.
    - It then creates a domain event object from the request payload.
    - Finally, it passes the event to a dispatcher to be routed to the
      correct application service.
    """
    # The 'is_verified' dependency handles raising an error on failure,
    # so we don't need to check its return value here.

    payload = await request.json()
    event_name = request.headers.get("X-GitHub-Event")

    # Log raw forced flag early for push events
    try:
        if event_name and event_name.split(".")[0] == "push":
            forced_flag = payload.get("forced", None)
            ref_value = payload.get("ref", "")
            logger.info(f"Webhook push received: forced={forced_flag}, ref={ref_value}")
    except Exception:
        pass

    try:
        event = _create_event_from_request(event_name, payload)
        result = await dispatcher_instance.dispatch(event)
        return {"status": "event dispatched successfully", "result": result}
    except HTTPException as e:
        # This allows us to gracefully handle unsupported events without
        # treating them as server errors.
        if e.status_code == 202:
            return {"status": "event received but not supported", "detail": e.detail}
        raise e
