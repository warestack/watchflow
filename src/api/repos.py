"""Repository-related API endpoints."""

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, status

from src.integrations.github.api import github_client

logger = structlog.get_logger()

router = APIRouter(prefix="/repos", tags=["Repositories"])


@router.get(
    "/{owner}/{repo}/installation",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Check GitHub App Installation",
    description="Check if the Watchflow GitHub App is installed for a given repository.",
)
async def check_installation(owner: str, repo: str) -> dict[str, Any]:
    """Check if Watchflow GitHub App is installed for repository."""
    repo_full_name = f"{owner}/{repo}"

    try:
        repo_data = await github_client.get_repository(repo_full_name=repo_full_name)
        if not repo_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repo_full_name}' not found or access denied.",
            )

        # TODO: Implement via GitHub App API /app/installations endpoint
        # Requires app JWT authentication to query installations
        return {"installed": False, "message": "Installation check not yet implemented."}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("installation_check_failed", repo=repo_full_name, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check installation: {str(e)}",
        ) from e
