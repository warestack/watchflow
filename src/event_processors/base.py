import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.core.models import WebhookEvent
from src.integrations.github import github_client
from src.rules.interface import RuleLoader
from src.rules.loaders.github_loader import GitHubRuleLoader
from src.tasks.task_queue import Task

logger = logging.getLogger(__name__)


class ProcessingState(str, Enum):
    """
    Processing state for event processing results.

    - PASS: Rules passed - everything is good, no violations found
    - FAIL: Rules failed - violations found, action required
    - ERROR: Error occurred - couldn't check, need to investigate
    """

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


class ProcessingResult(BaseModel):
    """Result of event processing."""

    state: ProcessingState
    violations: list[dict[str, Any]] = Field(default_factory=list)
    api_calls_made: int
    processing_time_ms: int
    error: str | None = None

    @property
    def success(self) -> bool:
        """
        Legacy property for backward compatibility.

        Returns True only for PASS state, False for FAIL or ERROR.
        Note: This doesn't distinguish between FAIL and ERROR.
        Use .state instead for explicit state checking.
        """
        return self.state == ProcessingState.PASS


class BaseEventProcessor(ABC):
    """Base class for all event processors."""

    def __init__(self):
        self.rule_provider = self._get_rule_provider()
        self.github_client = github_client

    @abstractmethod
    async def process(self, task: Task) -> ProcessingResult:
        """Process the event task."""
        raise NotImplementedError("Subclasses must implement process")

    @abstractmethod
    def get_event_type(self) -> str:
        """Get the event type this processor handles."""
        raise NotImplementedError("Subclasses must implement get_event_type")

    @abstractmethod
    async def prepare_webhook_data(self, task: Task) -> dict[str, Any]:
        """Prepare data from webhook payload."""
        raise NotImplementedError("Subclasses must implement prepare_webhook_data")

    @abstractmethod
    async def prepare_api_data(self, task: Task) -> dict[str, Any]:
        """Prepare data from GitHub API calls."""
        raise NotImplementedError("Subclasses must implement prepare_api_data")

    def _get_rule_provider(self) -> RuleLoader:
        """Get the rule provider for this processor."""
        return GitHubRuleLoader(github_client)

    async def _create_webhook_event(self, task: Task) -> WebhookEvent:
        """Create a WebhookEvent from the task."""
        from src.core.models import EventType

        return WebhookEvent(event_type=EventType(task.event_type), payload=task.payload)
