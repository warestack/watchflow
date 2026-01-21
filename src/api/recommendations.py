import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl

from src.agents.repository_analysis_agent.agent import RepositoryAnalysisAgent
from src.agents.repository_analysis_agent.models import RuleRecommendation
from src.api.dependencies import get_current_user_optional
from src.api.rate_limit import rate_limiter

# Internal: User model, auth assumed present—see core/api for details.
from src.core.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rules", tags=["Recommendations"])

# --- Models ---  # API schema—keep in sync with frontend expectations.


class AnalyzeRepoRequest(BaseModel):
    """
    Payload for repository analysis.
    """

    repo_url: HttpUrl = Field(
        ..., description="Full URL of the GitHub repository (e.g., https://github.com/pallets/flask)"
    )
    force_refresh: bool = Field(False, description="Bypass cache if true (Not yet implemented)")


class AnalysisResponse(BaseModel):
    """
    Standardized response for the frontend.
    """

    repository: str
    is_public: bool
    recommendations: list[RuleRecommendation]


# --- Helpers ---  # Utility—URL parsing brittle if GitHub changes format.


def parse_repo_from_url(url: str) -> str:
    """
    Extracts 'owner/repo' from a full GitHub URL.

    Args:
        url: The full URL string (e.g., https://github.com/owner/repo.git)

    Returns:
        str: 'owner/repo'

    Raises:
        ValueError: If the URL is not a valid GitHub repository URL.
    """
    clean_url = str(url).strip().rstrip("/").removesuffix(".git")

    # Accept raw "owner/repo"—user may paste shorthand.
    if "github.com" not in clean_url and len(clean_url.split("/")) == 2:
        return clean_url

    try:
        parts = clean_url.split("/")
        # Extract owner/repo—fragile if GitHub URL structure changes.
        if "github.com" in parts:
            idx = parts.index("github.com")
            if len(parts) > idx + 2:
                owner = parts[idx + 1]
                repo = parts[idx + 2]
                return f"{owner}/{repo}"
    except Exception:
        pass

    raise ValueError("Invalid GitHub repository URL. Must be in format 'https://github.com/owner/repo'.")


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
    Executes the Repository Analysis Agent.

    Flow:
    1. Parse and validate the Repo URL.
    2. Instantiate the RepositoryAnalysisAgent.
    3. Execute the agent (which handles its own GitHub API calls).
    4. Map the agent's internal result to the API response.
    """
    repo_url_str = str(payload.repo_url)
    client_ip = request.client.host if request.client else "unknown"
    user_id = user.email if user else "Anonymous"

    logger.info(f"Analysis requested for {repo_url_str} by {user_id} (IP: {client_ip})")

    # Step 1: Parse URL—fail fast if invalid.
    try:
        repo_full_name = parse_repo_from_url(repo_url_str)
    except ValueError as e:
        logger.warning(f"Invalid URL provided by {client_ip}: {repo_url_str}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    # Step 2: Rate limiting—TODO: use Redis. For now, agent handles GitHub 429s internally.

    # Step 3: Agent execution—public flow only. Private repo: expect 404/403, handled below.
    try:
        agent = RepositoryAnalysisAgent()
        result = await agent.execute(repo_full_name=repo_full_name, is_public=True)

    except Exception as e:
        logger.exception(f"Unexpected error during agent execution for {repo_full_name}")
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

    # Step 5: Success—extract recommendations, return API response.
    recommendations = result.data.get("recommendations", [])

    return AnalysisResponse(
        repository=repo_full_name,
        is_public=True,  # Phase 1: always public—future: support private with token
        recommendations=recommendations,
    )
