import logging
from typing import Any

from src.core.models import EventType, WebhookEvent
from src.webhooks.handlers.base import EventHandler  # Import the base handler

logger = logging.getLogger(__name__)


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
            logger.warning(f"Handler for event type {event_type} is being overridden.")
        self._handlers[event_type] = handler
        logger.info(f"Registered handler for {event_type.name}: {handler.__class__.__name__}")

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
            logger.warning(f"No handler registered for event type {event.event_type}. Skipping.")
            return {"status": "skipped", "reason": f"No handler for event type {event.event_type.name}"}

        try:
            handler_name = handler_instance.__class__.__name__
            logger.info(f"Dispatching event {event.event_type.name} to handler {handler_name}.")
            # Call the 'handle' method on the registered handler instance
            result = await handler_instance.handle(event)
            return {"status": "processed", "handler": handler_name, "result": result}
        except Exception as e:
            logger.exception(f"Error executing handler for event {event.event_type.name}: {e}")
            return {"status": "error", "reason": str(e)}


# The shared instance remains the same
dispatcher = WebhookDispatcher()
