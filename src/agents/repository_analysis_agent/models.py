# File: src/agents/repository_analysis_agent/models.py

from pydantic import BaseModel, Field


class RuleRecommendation(BaseModel):
    """
    Represents a single rule suggested by the AI.
    """

    key: str = Field(..., description="Unique identifier for the rule (e.g., 'require_pr_approvals')")
    name: str = Field(..., description="Human-readable title")
    description: str = Field(..., description="What the rule does")
    severity: str = Field("medium", description="low, medium, high, or critical")
    category: str = Field("quality", description="security, quality, compliance, or velocity")
    reasoning: str = Field(..., description="Why this rule was suggested based on the repo analysis")


class AnalysisState(BaseModel):
    """
    The Shared Memory (Blackboard) for the Analysis Agent.
    """

    # --- Inputs ---
    repo_full_name: str
    is_public: bool = False

    # --- Collected Signals (Raw Data) ---
    file_tree: list[str] = Field(default_factory=list, description="List of file paths in the repo")
    readme_content: str | None = None
    contributing_content: str | None = None
    detected_languages: list[str] = Field(default_factory=list)
    has_ci: bool = False
    has_codeowners: bool = False
    workflow_patterns: list[str] = Field(
        default_factory=list, description="Detected workflow patterns in .github/workflows/"
    )

    # --- Outputs ---
    recommendations: list[RuleRecommendation] = Field(default_factory=list)

    # --- Execution Metadata ---
    error: str | None = None
    step_log: list[str] = Field(default_factory=list)
