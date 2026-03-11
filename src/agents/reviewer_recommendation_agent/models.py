# File: src/agents/reviewer_recommendation_agent/models.py

from typing import Any

from pydantic import BaseModel, Field


class ReviewerCandidate(BaseModel):
    """A candidate reviewer with a score and reasons for recommendation."""

    username: str
    score: int = 0
    ownership_pct: int = 0  # % of changed files they own or recently touched
    reasons: list[str] = Field(default_factory=list)


class RiskSignal(BaseModel):
    """A single contributing factor to the PR risk score."""

    label: str
    description: str
    points: int


class LLMReviewerRanking(BaseModel):
    """Structured output from the LLM reviewer ranking step."""

    ranked_reviewers: list[dict[str, str]] = Field(
        description="Ordered list of {username, reason} dicts, best match first"
    )
    summary: str = Field(description="One-line overall recommendation summary")


class RecommendationState(BaseModel):
    """Shared state (blackboard) for the ReviewerRecommendationAgent graph."""

    # --- Inputs ---
    repo_full_name: str
    pr_number: int
    installation_id: int

    # --- Collected Data ---
    pr_files: list[str] = Field(default_factory=list)
    pr_author: str = ""
    pr_additions: int = 0
    pr_deletions: int = 0
    pr_commits_count: int = 0
    pr_author_association: str = "NONE"
    codeowners_content: str | None = None
    contributors: list[dict[str, Any]] = Field(default_factory=list)
    # file_path -> list of recent committer logins
    file_experts: dict[str, list[str]] = Field(default_factory=dict)

    # --- Risk Assessment ---
    risk_score: int = 0
    risk_level: str = "low"  # low / medium / high / critical
    risk_signals: list[RiskSignal] = Field(default_factory=list)

    # --- Recommendations ---
    candidates: list[ReviewerCandidate] = Field(default_factory=list)
    llm_ranking: LLMReviewerRanking | None = None

    # --- Execution Metadata ---
    error: str | None = None
