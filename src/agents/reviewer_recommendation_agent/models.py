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


class RankedReviewer(BaseModel):
    """A single reviewer entry in the LLM ranking output."""

    username: str = Field(description="GitHub username of the reviewer")
    reason: str = Field(description="Short explanation of why this reviewer is recommended")


class LLMReviewerRanking(BaseModel):
    """Structured output from the LLM reviewer ranking step."""

    ranked_reviewers: list[RankedReviewer] = Field(description="Ordered list of reviewers, best match first")
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
    # Matched Watchflow rules (description, severity) loaded from .watchflow/rules.yaml
    matched_rules: list[dict[str, str]] = Field(default_factory=list)
    # Recent review activity: login -> count of reviews on recent PRs (for load balancing)
    reviewer_load: dict[str, int] = Field(default_factory=dict)
    # Reviewer acceptance rates: login -> approval rate (0.0–1.0) from recent PRs
    reviewer_acceptance_rates: dict[str, float] = Field(default_factory=dict)
    # PR title (for revert detection)
    pr_title: str = ""

    # --- Risk Assessment ---
    risk_score: int = 0
    risk_level: str = "low"  # low / medium / high / critical
    risk_signals: list[RiskSignal] = Field(default_factory=list)

    # --- Recommendations ---
    candidates: list[ReviewerCandidate] = Field(default_factory=list)
    llm_ranking: LLMReviewerRanking | None = None

    # PR base branch (used when writing .watchflow/expertise.json)
    pr_base_branch: str = "main"
    # Team slugs extracted from CODEOWNERS (@org/team entries) — used to split
    # reviewer assignment into `reviewers` vs `team_reviewers` GitHub API fields
    codeowners_team_slugs: list[str] = Field(default_factory=list)
    # Persisted expertise profiles loaded from .watchflow/expertise.json
    expertise_profiles: dict[str, Any] = Field(default_factory=dict)

    # --- Execution Metadata ---
    error: str | None = None
