"""
Data models for the Reviewer Reasoning Agent.
"""

from pydantic import BaseModel, Field


class ReviewerProfile(BaseModel):
    """Expertise profile for a single reviewer candidate."""

    login: str = Field(description="GitHub username")
    mechanical_reason: str = Field(description="Scoring-based reason string", default="")
    languages: list[str] = Field(description="Programming languages the reviewer works with", default_factory=list)
    commit_count: int = Field(description="Total commits in the repo from expertise.yaml", default=0)
    reviews: dict[str, int] = Field(
        description="PRs reviewed by risk bucket plus total count",
        default_factory=lambda: {"total": 0, "low": 0, "medium": 0, "high": 0, "critical": 0},
    )
    last_active: str = Field(description="ISO date of last activity", default="")
    score: float = Field(description="Computed reviewer score", default=0.0)
    rule_mentions: list[str] = Field(
        description="Descriptions of matched rules that list this reviewer as a critical owner",
        default_factory=list,
    )


class ReviewerReasoningInput(BaseModel):
    """Input state for the reviewer reasoning agent."""

    risk_level: str = Field(description="PR risk level: low, medium, high, critical")
    changed_files: list[str] = Field(description="Sample of changed file paths", default_factory=list)
    risk_signals: list[str] = Field(description="Triggered risk signal descriptions", default_factory=list)
    reviewers: list[ReviewerProfile] = Field(description="Top reviewer candidates with profiles", default_factory=list)
    global_rules: list[str] = Field(
        description="Descriptions of matched rules that have no file_patterns (apply repo-wide)",
        default_factory=list,
    )
    path_rules: list[str] = Field(
        description="Descriptions of matched rules that have file_patterns (path-specific)",
        default_factory=list,
    )


class ReviewerExplanation(BaseModel):
    """A single reviewer's reasoning sentence."""

    login: str = Field(description="GitHub username of the reviewer")
    reasoning: str = Field(description="One concise sentence explaining why this reviewer is the best fit for this PR")


class RuleLabel(BaseModel):
    """Short human-readable topic label for a global (no file_patterns) rule."""

    description: str = Field(description="Original rule description, used as a key to match back")
    label: str = Field(description="Short topic label, e.g. 'test coverage', 'PR size limit', 'dependency changes'")


class ReviewerReasoningOutput(BaseModel):
    """Structured LLM output: one explanation per reviewer, plus labels for global rules."""

    explanations: list[ReviewerExplanation] = Field(description="One explanation per reviewer", default_factory=list)
    rule_labels: list[RuleLabel] = Field(
        description="Short topic labels for global rules (one entry per item in global_rules input)",
        default_factory=list,
    )
