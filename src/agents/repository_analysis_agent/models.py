# File: src/agents/repository_analysis_agent/models.py

from typing import Any

from pydantic import BaseModel, Field, model_validator


def parse_github_repo_identifier(identifier: str) -> str:
    """
    Normalizes various GitHub identifiers into 'owner/repo' format.
    Used by tests to verify repository strings.
    """
    # Remove protocol and domain
    clean_id = identifier.replace("https://github.com/", "").replace("http://github.com/", "")

    # Remove .git suffix and trailing slashes
    clean_id = clean_id.replace(".git", "").strip("/")

    return clean_id


class RepositoryAnalysisRequest(BaseModel):
    """
    Input request for analyzing a repository.
    Automatically normalizes the repository URL into a full name.
    """

    repository_full_name: str = Field(default="", description="GitHub repository in 'owner/repo' format")
    repository_url: str = Field(default="", description="Full GitHub repository URL (optional, will be normalized)")
    installation_id: int | None = Field(
        default=None, description="GitHub App installation ID for authenticated requests"
    )

    @model_validator(mode="after")
    def normalize_repo_name(self) -> "RepositoryAnalysisRequest":
        """Normalize repository URL to full name format."""
        if not self.repository_full_name and self.repository_url:
            self.repository_full_name = parse_github_repo_identifier(self.repository_url)
        return self


class RepositoryFeatures(BaseModel):
    """
    Extracted features from a repository used for analysis.
    """

    has_contributing: bool = Field(default=False, description="Has CONTRIBUTING.md file")
    has_codeowners: bool = Field(default=False, description="Has CODEOWNERS file")
    has_workflows: bool = Field(default=False, description="Has GitHub Actions workflows")
    contributor_count: int = Field(default=0, description="Number of contributors")
    detected_languages: list[str] = Field(default_factory=list, description="Programming languages detected")
    has_tests: bool = Field(default=False, description="Has test files or testing framework")


class RepositoryAnalysisResponse(BaseModel):
    """
    Response from repository analysis containing recommendations and metadata.
    """

    success: bool = Field(..., description="Whether the analysis completed successfully")
    message: str = Field(..., description="Status message or error description")
    repository_full_name: str = Field(..., description="The analyzed repository")
    recommendations: list["RuleRecommendation"] = Field(default_factory=list, description="List of recommended rules")
    features: RepositoryFeatures | None = Field(default=None, description="Extracted repository features")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional analysis metadata")


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
