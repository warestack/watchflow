from enum import Enum


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

    )
    category: str = Field(description="Category of the rule (e.g., 'quality', 'security', 'process')")
    estimated_impact: str = Field(description="Expected impact (e.g., 'high', 'medium', 'low')")


class RepositoryAnalysisRequest(BaseModel):
    """Request model for repository analysis."""

    repository_full_name: str = Field(description="Full repository name (owner/repo)")

    )


class RepositoryFeatures(BaseModel):
    """Features and characteristics discovered in the repository."""

    has_contributing: bool = Field(description="Has CONTRIBUTING.md file", default=False)
    has_codeowners: bool = Field(description="Has CODEOWNERS file", default=False)
    has_workflows: bool = Field(description="Has GitHub Actions workflows", default=False)
    has_branch_protection: bool = Field(description="Has branch protection rules", default=False)
    workflow_count: int = Field(description="Number of workflow files", default=0)

    contributor_count: int = Field(description="Number of contributors", default=0)
    pr_count: int = Field(description="Number of pull requests", default=0)
    issue_count: int = Field(description="Number of issues", default=0)


class ContributingGuidelinesAnalysis(BaseModel):
    """Analysis of contributing guidelines content."""


    has_pr_template: bool = Field(description="Requires PR templates", default=False)
    has_issue_template: bool = Field(description="Requires issue templates", default=False)
    requires_tests: bool = Field(description="Requires tests for contributions", default=False)
    requires_docs: bool = Field(description="Requires documentation updates", default=False)



class RepositoryAnalysisState(BaseModel):
    """State for the repository analysis workflow."""

    repository_full_name: str



class RepositoryAnalysisResponse(BaseModel):
    """Response model containing rule recommendations."""

    repository_full_name: str = Field(description="Repository that was analyzed")
