from .base import BaseEventProcessor
from .check_run import CheckRunProcessor
from .deployment import DeploymentProcessor
from .deployment_protection_rule import DeploymentProtectionRuleProcessor
from .deployment_review import DeploymentReviewProcessor
from .deployment_status import DeploymentStatusProcessor
from .pull_request import PullRequestProcessor
from .push import PushProcessor
from .rule_creation import RuleCreationProcessor
from .status import StatusProcessor
from .violation_acknowledgment import ViolationAcknowledgmentProcessor


class EventProcessorFactory:
    """Factory for creating event processors."""

    _processors: dict[str, type[BaseEventProcessor]] = {
        "pull_request": PullRequestProcessor,
        "push": PushProcessor,
        "check_run": CheckRunProcessor,
        "status": StatusProcessor,
        "deployment_review": DeploymentReviewProcessor,
        "deployment_status": DeploymentStatusProcessor,
        "deployment": DeploymentProcessor,  # Process deployment events for rule checking
        "deployment_protection_rule": DeploymentProtectionRuleProcessor,
        "rule_creation": RuleCreationProcessor,
        "violation_acknowledgment": ViolationAcknowledgmentProcessor,
    }

    @classmethod
    def create_processor(cls, event_type: str) -> BaseEventProcessor:
        """Create a processor for the given event type."""
        processor_class = cls._processors.get(event_type)
        if not processor_class:
            raise ValueError(f"No processor found for event type: {event_type}")

        return processor_class()

    @classmethod
    def register_processor(cls, event_type: str, processor_class: type[BaseEventProcessor]):
        """Register a new processor."""
        cls._processors[event_type] = processor_class

    @classmethod
    def get_processor(cls, event_type: str) -> BaseEventProcessor:
        """Get processor for the given event type."""
        processor_class = cls._processors.get(event_type)
        if not processor_class:
            raise ValueError(f"No processor found for event type: {event_type}")
        return processor_class()

    @classmethod
    def get_supported_event_types(cls) -> list:
        """Get list of supported event types."""
        return list(cls._processors.keys())
