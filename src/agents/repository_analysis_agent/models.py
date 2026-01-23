# File: src/agents/repository_analysis_agent/models.py

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


class RepoMetadata(BaseModel):
    """
    Structured repository metadata.
    """

    name: str
    owner: str
    default_branch: str
    language: str | None = None
    description: str | None = None
    stargazers_count: int = 0
    forks_count: int = 0
    open_issues_count: int = 0


class RepositoryAnalysisResponse(BaseModel):
    """
    Response from repository analysis containing recommendations and metadata.
    """

    success: bool = Field(..., description="Whether the analysis completed successfully")
    message: str = Field(..., description="Status message or error description")
    repository_full_name: str = Field(..., description="The analyzed repository")
    recommendations: list["RuleRecommendation"] = Field(default_factory=list, description="List of recommended rules")
    features: RepositoryFeatures | None = Field(default=None, description="Extracted repository features")
    metadata: RepoMetadata | None = Field(default=None, description="Additional analysis metadata")


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


class PRSignal(BaseModel):
    """
    Represents data from a single historical PR to detect AI spam or low-quality contributions.

    This model is a core component of the "AI Immune System" feature. It captures signals
    from merged PRs that indicate potential low-effort contributions, including:
    - Missing issue links (drive-by commits)
    - First-time contributors (higher risk profile)
    - AI-generated content markers (detected via heuristics)
    - Abnormal PR sizes (mass changes without context)

    These signals feed into HygieneMetrics to inform rule recommendations.
    """

    pr_number: int = Field(..., description="GitHub PR number for reference")
    has_linked_issue: bool = Field(..., description="Whether the PR references an issue (required for context)")
    author_association: str = Field(
        ..., description="GitHub author role: 'FIRST_TIME_CONTRIBUTOR', 'MEMBER', 'COLLABORATOR', etc."
    )
    is_ai_generated_hint: bool = Field(
        ..., description="Heuristic flag: True if PR description contains AI tool signatures (Claude, Cursor, etc.)"
    )
    lines_changed: int = Field(..., description="Total lines added + deleted (indicator of PR scope)")


class HygieneMetrics(BaseModel):
    """
    Aggregated repository signals for hygiene analysis.

    This model powers the "AI Immune System" by summarizing patterns across recent PRs.
    High unlinked_issue_rate or abnormal average_pr_size triggers defensive rules like:
    - require_linked_issue (force context)
    - max_pr_size (prevent mass changes)
    - first_time_contributor_review (extra scrutiny)

    These metrics are calculated from the last 20-30 merged PRs and inform LLM reasoning.
    """

    unlinked_issue_rate: float = Field(
        ...,
        description="Percentage (0.0-1.0) of PRs without linked issues. High values indicate poor governance.",
    )
    average_pr_size: int = Field(
        ..., description="Mean lines changed per PR. Unusually high values suggest untargeted contributions."
    )
    first_time_contributor_count: int = Field(
        ..., description="Count of unique first-time contributors in recent PRs (risk indicator)."
    )
    ci_skip_rate: float = Field(
        default=0.0,
        description="Percentage (0.0-1.0) of PRs that skip CI checks via commit message.",
    )
    codeowner_bypass_rate: float = Field(
        default=0.0,
        description="Percentage (0.0-1.0) of PRs merged without required CODEOWNER approval. Detects governance violations.",
    )
    new_code_test_coverage: float = Field(
        default=0.0,
        description="Average ratio of test line additions relative to source code changes. Low values indicate untested contributions.",
    )
    issue_diff_mismatch_rate: float = Field(
        default=0.0,
        description="Percentage (0.0-1.0) of PRs where the linked issue doesn't semantically match the code diff. Detects low-effort contributions claiming to fix unrelated issues.",
    )
    ghost_contributor_rate: float = Field(
        default=0.0,
        description="Percentage (0.0-1.0) of PRs where the author never responded to review comments. Indicates drive-by contributions with no engagement.",
    )
    ai_generated_rate: float | None = Field(
        default=None,
        description="Percentage (0.0-1.0) of PRs flagged as AI-generated based on heuristic signatures (e.g., 'generated by Claude', 'Cursor'). Detects bulk AI spam.",
    )


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
    pr_signals: list[PRSignal] = Field(default_factory=list, description="Historical PR signals for hygiene analysis")
    hygiene_summary: HygieneMetrics | None = None

    # --- Outputs ---
    recommendations: list[RuleRecommendation] = Field(default_factory=list)

    # --- Execution Metadata ---
    error: str | None = None
    step_log: list[str] = Field(default_factory=list)
