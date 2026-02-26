from typing import Any

import structlog

from src.core.models import EventType, WebhookEvent
from src.core.utils.event_filter import should_process_event
from src.webhooks.handlers.base import EventHandler  # Import the base handler

logger = structlog.get_logger()


class WebhookDispatcher:
    """
    Dispatches webhook events to registered EventHandler instances.
    """

    def __init__(self):
        # The registry now maps an EventType to an instance of an EventHandler class
        self._handlers: dict[EventType, EventHandler] = {}

    def register_handler(self, event_type: EventType, handler: EventHandler):
        """
        Registers a handler instance for a specific event type.

        Args:
            event_type: The EventType to handle (e.g., EventType.PULL_REQUEST).
            handler: An instance of a class that implements the EventHandler interface.
        """
        if event_type in self._handlers:
            logger.warning("handler_overridden", event_type=event_type.name)
        self._handlers[event_type] = handler
        logger.info("handler_registered", event_type=event_type.name, handler=handler.__class__.__name__)

    async def dispatch(self, event: WebhookEvent) -> dict[str, Any]:
        """
        Looks up and executes the .handle() method of the appropriate handler
        for the given event.

        Args:
            event: The WebhookEvent to be dispatched.

        Returns:
            A dictionary containing the result from the handler.
        """
        handler_instance = self._handlers.get(event.event_type)

        if not handler_instance:
            logger.warning(
                "handler_not_found",
                operation="dispatch",
                subject_ids={"repo": event.repo_full_name},
                event_type=event.event_type.name,
            )
            return {"status": "skipped", "reason": f"No handler for event type {event.event_type.name}"}

        # Apply event filtering before dispatching
        filter_result = should_process_event(event)
        if not filter_result.should_process:
            logger.info(
                "event_filtered",
                operation="dispatch",
                subject_ids={"repo": event.repo_full_name},
                event_type=event.event_type.name,
                reason=filter_result.reason,
            )
            return {"status": "filtered", "reason": filter_result.reason, "event_type": event.event_type.name}

        try:
            handler_name = handler_instance.__class__.__name__
            logger.info(
                "dispatching_event",
                operation="dispatch",
                subject_ids={"repo": event.repo_full_name},
                event_type=event.event_type.name,
                handler=handler_name,
            )
            # Call the 'handle' method on the registered handler instance
            result = await handler_instance.handle(event)
            return {"status": "processed", "handler": handler_name, "result": result}
        except Exception as e:
            logger.exception(
                "handler_error",
                operation="dispatch",
                subject_ids={"repo": event.repo_full_name},
                event_type=event.event_type.name,
                error=str(e),
            )
            return {"status": "error", "reason": str(e)}


# The shared instance remains the same
dispatcher = WebhookDispatcher()
