from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, SecretStr, field_validator


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
    github_token: SecretStr | None = Field(None, description="OAuth token for GitHub API access", exclude=True)


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


class HygieneMetrics(BaseModel):
    """
    Aggregated repository signals for hygiene analysis.
    This is the canonical model used across agents and rules.
    """

    unlinked_issue_rate: float = Field(
        default=0.0,
        description="Percentage (0.0-1.0) of PRs without linked issues. High values indicate poor governance.",
    )
    average_pr_size: int = Field(
        default=0, description="Mean lines changed per PR. Unusually high values suggest untargeted contributions."
    )
    first_time_contributor_count: int = Field(
        default=0, description="Count of unique first-time contributors in recent PRs (risk indicator)."
    )
    ci_skip_rate: float = Field(
        default=0.0,
        description="Percentage (0.0-1.0) of PRs that skip CI checks via commit message.",
    )
    codeowner_bypass_rate: float = Field(
        default=0.0,
        description="Percentage (0.0-1.0) of PRs merged without required CODEOWNER approval.",
    )
    new_code_test_coverage: float = Field(
        default=0.0,
        description="Average ratio of test line additions relative to source code changes.",
    )
    issue_diff_mismatch_rate: float = Field(
        default=0.0,
        description="Percentage (0.0-1.0) of PRs where the linked issue doesn't semantically match the code diff.",
    )
    ghost_contributor_rate: float = Field(
        default=0.0,
        description="Percentage (0.0-1.0) of PRs where the author never responded to review comments.",
    )
    ai_generated_rate: float | None = Field(
        default=None,
        description="Percentage (0.0-1.0) of PRs flagged as AI-generated based on heuristic signatures.",
    )

    @field_validator(
        "unlinked_issue_rate",
        "ci_skip_rate",
        "codeowner_bypass_rate",
        "new_code_test_coverage",
        "issue_diff_mismatch_rate",
        "ghost_contributor_rate",
        "ai_generated_rate",
        mode="before",
    )
    @classmethod
    def validate_rate(cls, v: float | None) -> float | None:
        if v is None:
            return None
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Rate must be between 0.0 and 1.0, got {v}")
        return v
