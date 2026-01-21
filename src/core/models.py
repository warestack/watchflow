from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class User(BaseModel):
    """
    Represents an authenticated user in the system.
    Used for dependency injection in API endpoints.
    """

    id: int
    username: str
    email: str | None = None
    avatar_url: str | None = None
    # storing the token allows the service layer to make requests on behalf of the user
    github_token: str | None = Field(None, description="OAuth token for GitHub API access")


# --- Event Definitions (Legacy/Core Architecture) ---


class EventType(str, Enum):
    """
    Supported GitHub Event Types.
    Reference: project_detail_med.md [cite: 32]
    """

    PUSH = "push"
    ISSUE_COMMENT = "issue_comment"
    PULL_REQUEST = "pull_request"
    CHECK_RUN = "check_run"
    DEPLOYMENT = "deployment"
    DEPLOYMENT_STATUS = "deployment_status"
    DEPLOYMENT_REVIEW = "deployment_review"
    DEPLOYMENT_PROTECTION_RULE = "deployment_protection_rule"
    WORKFLOW_RUN = "workflow_run"


class WebhookEvent:
    """
    Encapsulates a GitHub webhook event.
    Currently a plain Python class for efficiency, but validates against EventType.
    Reference: project_detail_med.md [cite: 33]
    """

    def __init__(self, event_type: EventType, payload: dict[str, Any]):
        self.event_type = event_type
        self.payload = payload
        self.repository = payload.get("repository", {})
        self.sender = payload.get("sender", {})
        self.installation_id = payload.get("installation", {}).get("id")

    @property
    def repo_full_name(self) -> str:
        """Helper to safely get 'owner/repo' string."""
        return self.repository.get("full_name", "")

    @property
    def sender_login(self) -> str:
        """Helper to safely get the username of the event sender."""
        return self.sender.get("login", "")
