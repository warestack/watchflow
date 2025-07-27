from enum import Enum
from typing import Any


class EventType(Enum):
    """Supported GitHub event types."""

    PUSH = "push"
    ISSUE_COMMENT = "issue_comment"
    PULL_REQUEST = "pull_request"
    CHECK_RUN = "check_run"
    STATUS = "status"
    DEPLOYMENT = "deployment"
    DEPLOYMENT_STATUS = "deployment_status"
    DEPLOYMENT_REVIEW = "deployment_review"
    DEPLOYMENT_PROTECTION_RULE = "deployment_protection_rule"
    WORKFLOW_RUN = "workflow_run"
    # Add other event types here as we support them


class WebhookEvent:
    """
    A representation of an incoming webhook event, before it has been
    fully prepared and enriched by our integration logic.
    """

    def __init__(self, event_type: EventType, payload: dict[str, Any]):
        self.event_type = event_type
        self.payload = payload
        self.repository = payload.get("repository", {})
        self.sender = payload.get("sender", {})
        self.installation_id = payload.get("installation", {}).get("id")

    @property
    def repo_full_name(self) -> str:
        """The full name of the repository (e.g., 'owner/repo')."""
        return self.repository.get("full_name", "")

    @property
    def sender_login(self) -> str:
        """The GitHub username of the user who triggered the event."""
        return self.sender.get("login", "")
