

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



class PullRequestSample(BaseModel):
    """Minimal PR snapshot used for recommendations."""




class RepositoryFeatures(BaseModel):
    """Features and characteristics discovered in the repository."""




class ContributingGuidelinesAnalysis(BaseModel):
    """Analysis of contributing guidelines content."""



class RepositoryAnalysisState(BaseModel):
    """State for the repository analysis workflow."""

    repository_full_name: str



class RepositoryAnalysisResponse(BaseModel):
    """Response model containing rule recommendations and PR plan."""

    repository_full_name: str = Field(description="Repository that was analyzed")
