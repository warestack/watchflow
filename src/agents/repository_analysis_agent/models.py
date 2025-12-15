from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def parse_github_repo_identifier(value: str) -> str:
    """
    Normalize a GitHub repository identifier.

    Accepts:
    - owner/repo
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - owner/repo/
    """
    raw = (value or "").strip()
    if not raw:
        return ""

    if raw.startswith("https://") or raw.startswith("http://"):
        parts = raw.split("/")
        try:
            gh_idx = parts.index("github.com")
        except ValueError:
            # Could be enterprise; keep as-is and let API validation fail.
            return raw.rstrip("/").removesuffix(".git")

        owner = parts[gh_idx + 1] if len(parts) > gh_idx + 1 else ""
        repo = parts[gh_idx + 2] if len(parts) > gh_idx + 2 else ""
        return f"{owner}/{repo}".rstrip("/").removesuffix(".git")

    return raw.rstrip("/").removesuffix(".git")


class PullRequestSample(BaseModel):
    """Minimal PR snapshot used for recommendations."""

    number: int
    title: str
    state: str
    merged: bool = False
    additions: int | None = None
    deletions: int | None = None
    changed_files: int | None = None


class RuleRecommendation(BaseModel):
    """A recommended Watchflow rule with confidence and reasoning."""

    yaml_rule: str = Field(description="Valid Watchflow rule YAML content")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0)
    reasoning: str = Field(description="Short explanation of why this rule is recommended")
    strategy_used: str = Field(description="Strategy used (static, hybrid, llm)")


class RepositoryFeatures(BaseModel):
    """Features and characteristics discovered in the repository."""

    has_contributing: bool = Field(default=False, description="Has CONTRIBUTING.md file")
    has_codeowners: bool = Field(default=False, description="Has CODEOWNERS file")
    has_workflows: bool = Field(default=False, description="Has GitHub Actions workflows")
    workflow_count: int = Field(default=0, description="Number of workflow files")
    language: str | None = Field(default=None, description="Primary programming language")
    contributor_count: int = Field(default=0, description="Number of contributors")
    pr_count: int = Field(default=0, description="Number of pull requests")


class ContributingGuidelinesAnalysis(BaseModel):
    """Analysis of contributing guidelines content."""

    content: str | None = Field(default=None, description="Full CONTRIBUTING.md content")
    has_pr_template: bool = Field(default=False, description="Requires PR templates")
    has_issue_template: bool = Field(default=False, description="Requires issue templates")
    requires_tests: bool = Field(default=False, description="Requires tests for contributions")
    requires_docs: bool = Field(default=False, description="Requires documentation updates")
    code_style_requirements: list[str] = Field(default_factory=list, description="Code style requirements mentioned")
    review_requirements: list[str] = Field(default_factory=list, description="Code review requirements mentioned")


class PullRequestPlan(BaseModel):
    """Plan for creating a PR with generated rules."""

    branch_name: str = "watchflow/rules"
    base_branch: str = "main"
    commit_message: str = "chore: add Watchflow rules"
    pr_title: str = "Add Watchflow rules"
    pr_body: str = "This PR adds Watchflow rule recommendations."
    file_path: str = ".watchflow/rules.yaml"


class RepositoryAnalysisRequest(BaseModel):
    """Request model for repository analysis."""

    repository_url: str | None = Field(default=None, description="GitHub repository URL")
    repository_full_name: str | None = Field(default=None, description="Full repository name (owner/repo)")
    installation_id: int | None = Field(default=None, description="GitHub App installation ID")
    max_prs: int = Field(default=10, ge=0, le=50, description="Max PRs to sample for analysis")

    @field_validator("repository_full_name", mode="before")
    @classmethod
    def normalize_full_name(cls, value: str | None, info) -> str:
        if value:
            return parse_github_repo_identifier(value)
        raw_url = info.data.get("repository_url")
        return parse_github_repo_identifier(raw_url or "")

    @field_validator("repository_url", mode="before")
    @classmethod
    def strip_url(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def populate_full_name(self) -> "RepositoryAnalysisRequest":
        if not self.repository_full_name and self.repository_url:
            self.repository_full_name = parse_github_repo_identifier(self.repository_url)
        return self


class RepositoryAnalysisState(BaseModel):
    """State for the repository analysis workflow."""

    repository_full_name: str
    installation_id: int | None
    pr_samples: list[PullRequestSample] = Field(default_factory=list)
    repository_features: RepositoryFeatures = Field(default_factory=RepositoryFeatures)
    contributing_analysis: ContributingGuidelinesAnalysis = Field(default_factory=ContributingGuidelinesAnalysis)
    recommendations: list[RuleRecommendation] = Field(default_factory=list)
    rules_yaml: str | None = None
    pr_plan: PullRequestPlan | None = None
    analysis_summary: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class RepositoryAnalysisResponse(BaseModel):
    """Response model containing rule recommendations and PR plan."""

    repository_full_name: str = Field(description="Repository that was analyzed")
    rules_yaml: str = Field(description="Combined Watchflow rules YAML")
    recommendations: list[RuleRecommendation] = Field(default_factory=list, description="Rule recommendations")
    pr_plan: PullRequestPlan | None = Field(default=None, description="Suggested PR plan")
    analysis_summary: dict[str, Any] = Field(default_factory=dict, description="Summary of analysis findings")
    analyzed_at: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of analysis")


class ProceedWithPullRequestRequest(BaseModel):
    """Request to create a PR with generated rules."""

    repository_url: str | None = Field(default=None, description="GitHub repository URL")
    repository_full_name: str | None = Field(default=None, description="Full repository name (owner/repo)")
    installation_id: int | None = Field(default=None, description="GitHub App installation ID")
    user_token: str | None = Field(default=None, description="User token for GitHub operations (optional)")
    rules_yaml: str = Field(description="Rules YAML content to commit")
    branch_name: str = Field(default="watchflow/rules", description="Branch to create or update")
    base_branch: str = Field(default="main", description="Base branch for the PR")
    commit_message: str = Field(default="chore: add Watchflow rules", description="Commit message")
    pr_title: str = Field(default="Add Watchflow rules", description="Pull request title")
    pr_body: str = Field(default="This PR adds Watchflow rule recommendations.", description="Pull request body")
    file_path: str = Field(default=".watchflow/rules.yaml", description="Path to rules file in repo")

    @field_validator("repository_full_name", mode="before")
    @classmethod
    def normalize_full_name(cls, value: str | None, info) -> str:
        if value:
            return parse_github_repo_identifier(value)
        raw_url = info.data.get("repository_url")
        return parse_github_repo_identifier(raw_url or "")

    @model_validator(mode="after")
    def populate_full_name(self) -> "ProceedWithPullRequestRequest":
        if not self.repository_full_name and self.repository_url:
            self.repository_full_name = parse_github_repo_identifier(self.repository_url)
        return self


class ProceedWithPullRequestResponse(BaseModel):
    """Response after creating the PR."""

    pull_request_url: str
    branch_name: str
    base_branch: str
    file_path: str
    commit_sha: str | None = None
