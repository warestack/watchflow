import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from src.core.models import EventType, WebhookEvent
from src.webhooks.auth import verify_github_signature
from src.webhooks.dispatcher import WebhookDispatcher, dispatcher

logger = logging.getLogger(__name__)
router = APIRouter()


# DI for dispatcher—testability, lifecycle control.
def get_dispatcher() -> WebhookDispatcher:
    """Returns the shared WebhookDispatcher instance."""
    return dispatcher


def _create_event_from_request(event_name: str | None, payload: dict) -> WebhookEvent:
    """Factory function to create a WebhookEvent from raw request data."""
    if not event_name:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

    # GitHub sometimes sends event names with dot suffixes—strip for enum match.
    normalized_event_name = event_name.split(".")[0]
    logger.info(f"Received event: {event_name}, normalized: {normalized_event_name}")

    try:
        # Enum mapping—fail if GitHub adds new event type we don't support.
        event_type = EventType(normalized_event_name)
    except ValueError as e:
        logger.warning(f"Received an unsupported event type: {event_name} - {e}")
        # Defensive: Accept unknown events, but don't process—avoids GitHub retries/spam.
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
    # Signature check handled by dependency—fail fast if invalid.

    payload = await request.json()
    event_name = request.headers.get("X-GitHub-Event")

    try:
        event = _create_event_from_request(event_name, payload)
        result = await dispatcher_instance.dispatch(event)
        return {"status": "event dispatched successfully", "result": result}
    except HTTPException as e:
        # Don't 500 on unknown event—keeps GitHub happy, avoids alert noise.
        if e.status_code == 202:
            return {"status": "event received but not supported", "detail": e.detail}
        raise e
