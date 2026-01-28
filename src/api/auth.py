from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.integrations.github.api import GitHubClient

router = APIRouter()


class TokenValidationRequest(BaseModel):
    token: str


class TokenValidationResponse(BaseModel):
    valid: bool
    user_login: str | None = None
    scopes: list[str] = []
    message: str | None = None


class InstallationCheckResponse(BaseModel):
    installed: bool
    installation_id: int | None = None
    permissions: dict[str, str] = {}
    message: str | None = None


@router.post("/auth/validate-token", response_model=TokenValidationResponse)
async def validate_token(request: TokenValidationRequest):
    """
    Validates a GitHub Personal Access Token (PAT).
    """
    from structlog import get_logger

    logger = get_logger()

    try:
        # Use a temporary client to check the token
        client = GitHubClient(token=request.token)
        user = await client.get_authenticated_user()

        if not user:
            return TokenValidationResponse(valid=False, message="Invalid token")

        return TokenValidationResponse(
            valid=True,
            user_login=user.get("login"),
            scopes=[],  # To get scopes we'd need to inspect headers, which GitHubClient might obscure.
            # For now, successful user fetch confirms validity.
            message="Token is valid",
        )
    except Exception as e:
        # Security: Do not leak exception details to client
        logger.error("token_validation_failed", error=str(e))
        return TokenValidationResponse(valid=False, message="Token validation failed. Please check your credentials.")


@router.get("/repos/{owner}/{repo}/installation", response_model=InstallationCheckResponse)
async def check_installation(owner: str, repo: str):
    """
    Checks if the GitHub App is installed on the given repository.
    """
    from src.integrations.github.api import github_client  # Use the global app client for this check

    try:
        # We need to find the installation for this repo
        # Typically requires JWT auth as App to search installations

        # Note: listing all installations and filtering is inefficient.
        # Better: Try to get installation for repo directly.

        installation = await github_client.get_repo_installation(owner, repo)

        if installation:
            return InstallationCheckResponse(
                installed=True,
                installation_id=installation.get("id"),
                permissions=installation.get("permissions", {}),
                message="Installation found",
            )
        else:
            return InstallationCheckResponse(installed=False, message="App not installed on this repository")

    except HTTPException:
        # Re-raise HTTP exceptions (expected errors)
        raise
    except Exception as e:
        # Log full error internally, return generic message to client
        from structlog import get_logger

        logger = get_logger()
        logger.error("installation_check_failed", error=str(e), exc_info=True)
        return InstallationCheckResponse(installed=False, message="Unable to verify installation status")
