from abc import ABC, abstractmethod
from typing import Any

from src.core.models import WebhookEvent


class EventHandler(ABC):
    """
    Abstract base class for all webhook event handlers.

    Each implementation of this class is responsible for the end-to-end
    processing of a specific type of webhook event.
    """

    @abstractmethod
    async def handle(self, event: WebhookEvent) -> dict[str, Any]:
        """
        Process the incoming webhook event.

        Args:
            event: The validated and parsed WebhookEvent object.

        Returns:
            A dictionary containing the results of the handling logic.
        """
        raise NotImplementedError("Subclasses must implement handle")
