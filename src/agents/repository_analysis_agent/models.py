from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AnalysisSource(str, Enum):
    """Sources of analysis data for rule recommendations."""

    CONTRIBUTING_GUIDELINES = "contributing_guidelines"
    REPOSITORY_STRUCTURE = "repository_structure"
    WORKFLOWS = "workflows"
    BRANCH_PROTECTION = "branch_protection"
    COMMIT_PATTERNS = "commit_patterns"
    PR_PATTERNS = "pr_patterns"


class RuleRecommendation(BaseModel):
    """A recommended Watchflow rule with confidence and reasoning."""

    yaml_content: str = Field(description="Valid Watchflow rule YAML content")
    confidence: float = Field(
        description="Confidence score (0.0-1.0) in the recommendation",
        ge=0.0,
        le=1.0
    )
    reasoning: str = Field(description="Explanation of why this rule is recommended")
    source_patterns: List[str] = Field(
        description="Repository patterns that led to this recommendation",
        default_factory=list
    )
    category: str = Field(description="Category of the rule (e.g., 'quality', 'security', 'process')")
    estimated_impact: str = Field(description="Expected impact (e.g., 'high', 'medium', 'low')")


class RepositoryAnalysisRequest(BaseModel):
    """Request model for repository analysis."""

    repository_full_name: str = Field(description="Full repository name (owner/repo)")
    installation_id: Optional[int] = Field(
        description="GitHub App installation ID for accessing private repos",
        default=None
    )


class RepositoryFeatures(BaseModel):
    """Features and characteristics discovered in the repository."""

    has_contributing: bool = Field(description="Has CONTRIBUTING.md file", default=False)
    has_codeowners: bool = Field(description="Has CODEOWNERS file", default=False)
    has_workflows: bool = Field(description="Has GitHub Actions workflows", default=False)
    has_branch_protection: bool = Field(description="Has branch protection rules", default=False)
    workflow_count: int = Field(description="Number of workflow files", default=0)
    language: Optional[str] = Field(description="Primary programming language", default=None)
    contributor_count: int = Field(description="Number of contributors", default=0)
    pr_count: int = Field(description="Number of pull requests", default=0)
    issue_count: int = Field(description="Number of issues", default=0)


class ContributingGuidelinesAnalysis(BaseModel):
    """Analysis of contributing guidelines content."""

    content: Optional[str] = Field(description="Full CONTRIBUTING.md content", default=None)
    has_pr_template: bool = Field(description="Requires PR templates", default=False)
    has_issue_template: bool = Field(description="Requires issue templates", default=False)
    requires_tests: bool = Field(description="Requires tests for contributions", default=False)
    requires_docs: bool = Field(description="Requires documentation updates", default=False)
    code_style_requirements: List[str] = Field(
        description="Code style requirements mentioned",
        default_factory=list
    )
    review_requirements: List[str] = Field(
        description="Code review requirements mentioned",
        default_factory=list
    )


class RepositoryAnalysisState(BaseModel):
    """State for the repository analysis workflow."""

    repository_full_name: str
    installation_id: Optional[int]

    # Analysis data
    repository_features: RepositoryFeatures = Field(default_factory=RepositoryFeatures)
    contributing_analysis: ContributingGuidelinesAnalysis = Field(
        default_factory=ContributingGuidelinesAnalysis
    )

    # Processing state
    analysis_steps: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    # Results
    recommendations: List[RuleRecommendation] = Field(default_factory=list)
    analysis_summary: Dict[str, Any] = Field(default_factory=dict)


class RepositoryAnalysisResponse(BaseModel):
    """Response model containing rule recommendations."""

    repository_full_name: str = Field(description="Repository that was analyzed")
    recommendations: List[RuleRecommendation] = Field(
        description="List of recommended Watchflow rules",
        default_factory=list
    )
    analysis_summary: Dict[str, Any] = Field(
        description="Summary of analysis findings",
        default_factory=dict
    )
    analyzed_at: str = Field(description="Timestamp of analysis")
    total_recommendations: int = Field(description="Total number of recommendations made")
