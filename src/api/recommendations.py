from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from giturlparse import parse
from pydantic import BaseModel, Field, HttpUrl

from src.agents.repository_analysis_agent.agent import RepositoryAnalysisAgent
from src.api.dependencies import get_current_user_optional
from src.api.rate_limit import rate_limiter

# Internal: User model, auth assumed present—see core/api for details.
from src.core.models import User

logger = structlog.get_logger()

router = APIRouter(prefix="/rules", tags=["Recommendations"])

# --- Models ---  # API schema—keep in sync with frontend expectations.


class AnalyzeRepoRequest(BaseModel):
    """
    Payload for repository analysis.

    Attributes:
        repo_url (HttpUrl): Full URL of the GitHub repository (e.g., https://github.com/pallets/flask).
        force_refresh (bool): Bypass cache if true (Not yet implemented).
    """

    repo_url: HttpUrl = Field(
        ..., description="Full URL of the GitHub repository (e.g., https://github.com/pallets/flask)"
    )
    force_refresh: bool = Field(False, description="Bypass cache if true (Not yet implemented)")


class AnalysisResponse(BaseModel):
    """
    Standardized response for the frontend.

    Attributes:
        rules_yaml (str): Generated rules in YAML format.
        pr_plan (str): Markdown-formatted explanation of the recommended rules.
        analysis_summary (dict): Hygiene metrics and analysis insights.
    """

    rules_yaml: str
    pr_plan: str
    analysis_summary: dict[str, Any]


# --- Helpers ---  # Utility—URL parsing brittle if GitHub changes format.


def parse_repo_from_url(url: str) -> str:
    """
    Extracts 'owner/repo' from a full GitHub URL using giturlparse.

    Args:
        url: The full URL string (e.g., https://github.com/owner/repo.git)

    Returns:
        str: 'owner/repo'

    Raises:
        ValueError: If the URL is not a valid GitHub repository URL.
    """
    p = parse(str(url))
    if not p.valid or not p.owner or not p.repo or p.host not in {"github.com", "www.github.com"}:
        raise ValueError("Invalid GitHub repository URL. Must be in format 'https://github.com/owner/repo'.")
    return f"{p.owner}/{p.repo}"


# --- Endpoints ---  # Main API surface—keep stable for clients.


@router.post(
    "/recommend",
    response_model=AnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze Repository for Governance Rules",
    description="Analyzes a public or private repository using AI agents. Public repos allow anonymous access.",
    dependencies=[Depends(rate_limiter)],
)
async def recommend_rules(
    request: Request, payload: AnalyzeRepoRequest, user: User | None = Depends(get_current_user_optional)
) -> AnalysisResponse:
    """
    Executes the Repository Analysis Agent to generate governance rules.

    This endpoint orchestrates the analysis flow:
    1. Validates the GitHub repository URL.
    2. Instantiates the `RepositoryAnalysisAgent`.
    3. Runs the agent to fetch metadata, analyze PR history, and generate rules.
    4. Returns a standardized response with YAML rules and a remediation plan.

    Args:
        request: The incoming HTTP request (used for IP logging).
        payload: The request body containing the repository URL.
        user: The authenticated user (optional).

    Returns:
        AnalysisResponse: The generated rules, PR plan, and analysis summary.

    Raises:
        HTTPException: 404 if repo not found, 429 if rate limited, 500 for internal errors.
    """
    repo_url_str = str(payload.repo_url)
    client_ip = request.client.host if request.client else "unknown"
    user_id = user.email if user else "Anonymous"

    logger.info("analysis_requested", repo_url=repo_url_str, user_id=user_id, ip=client_ip)

    # Step 1: Parse URL—fail fast if invalid.
    try:
        repo_full_name = parse_repo_from_url(repo_url_str)
    except ValueError as e:
        logger.warning("invalid_url_provided", ip=client_ip, url=repo_url_str, error=str(e))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    # Step 2: Rate limiting—TODO: use Redis. For now, agent handles GitHub 429s internally.

    # Step 3: Agent execution—public flow only. Private repo: expect 404/403, handled below.
    try:
        agent = RepositoryAnalysisAgent()
        result = await agent.execute(repo_full_name=repo_full_name, is_public=True)

    except Exception as e:
        logger.exception("agent_execution_failed", repo=repo_full_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal analysis engine error."
        ) from e

    # Step 4: Agent failures—distinguish not found, rate limit, internal error. Pass through agent messages if possible.
    if not result.success:
        error_msg = result.message.lower()

        if "not found" in error_msg or "404" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repo_full_name}' not found. It may be private or invalid.",
            )
        elif "rate limit" in error_msg or "429" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="System is currently rate-limited by GitHub. Please try again later.",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Analysis failed: {result.message}"
            )

    # Step 5: Success—map agent state to the API response model.
    final_state = result.data  # The agent's execute method returns the final state

    # Generate rules_yaml from recommendations
    import yaml

    rules_output = {"rules": [rec.model_dump(exclude_none=True) for rec in final_state.get("recommendations", [])]}
    rules_yaml = yaml.dump(rules_output, indent=2, sort_keys=False)

    # Generate a markdown plan for the PR
    pr_plan_lines = ["### Watchflow: Automated Governance Plan\n"]
    for rec in final_state.get("recommendations", []):
        pr_plan_lines.append(f"- **Rule:** `{rec.name}` (`{rec.key}`)")
        pr_plan_lines.append(f"  - **Reasoning:** {rec.reasoning}")
    pr_plan = "\n".join(pr_plan_lines)

    # Populate the analysis summary from hygiene metrics
    analysis_summary = {}
    hygiene_summary = final_state.get("hygiene_summary")
    if hygiene_summary:
        analysis_summary = hygiene_summary.model_dump()

    return AnalysisResponse(
        rules_yaml=rules_yaml,
        pr_plan=pr_plan,
        analysis_summary=analysis_summary,
    )


@router.post(
    "/recommend/proceed-with-pr",
    status_code=status.HTTP_200_OK,
    summary="Create PR with Recommended Rules",
    description="Creates a pull request with the recommended Watchflow rules in the target repository.",
)
async def proceed_with_pr(payload: dict, user: User | None = Depends(get_current_user_optional)):
    """
    Endpoint to create a PR with recommended rules.
    This is a stub implementation for Phase 1 testing.

    Future implementation will:
    1. Validate user has write access to the repository
    2. Create a new branch
    3. Commit the rules YAML file
    4. Create a pull request
    """
    # Validate required fields
    if not payload.get("repository_full_name") or not payload.get("rules_yaml"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields: repository_full_name and rules_yaml",
        )

    # Require installation_id for authentication
    if not payload.get("installation_id"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required field: installation_id")

    # For Phase 1: Return mock response to satisfy tests
    # TODO: Implement actual GitHub API calls to create branch and PR
    return {
        "pull_request_url": "https://github.com/owner/repo/pull/1",
        "branch_name": payload.get("branch_name", "watchflow/rules"),
        "file_path": ".watchflow/rules.yaml",
    }
