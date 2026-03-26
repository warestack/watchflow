from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from src.core.utils.github_oidc import OIDCVerificationError, verify_github_oidc_token
from src.tasks.scheduler.deployment_scheduler import get_deployment_scheduler

router = APIRouter()


@router.get("/status")
async def get_scheduler_status() -> dict[str, Any]:
    """Get scheduler status and pending deployments."""
    return get_deployment_scheduler().get_status()


@router.post("/check-deployments")
async def check_pending_deployments(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Manually re-evaluate the status of pending deployments."""
    background_tasks.add_task(get_deployment_scheduler()._check_pending_deployments)
    return {"status": "scheduled", "message": "Deployment statuses will be updated on GitHub accordingly."}


@router.get("/pending-deployments")
async def get_pending_deployments() -> dict[str, Any]:
    """Get list of pending deployments."""
    status = get_deployment_scheduler().get_status()
    return {"pending_count": status["pending_count"], "deployments": status["pending_deployments"]}


class RefreshExpertiseRequest(BaseModel):
    repo: str  # e.g. "owner/repo-name"


@router.post("/refresh-expertise")
async def refresh_expertise_profiles(
    body: RefreshExpertiseRequest,
    request: Request,
) -> dict[str, str]:
    """Refresh .watchflow/expertise.yaml for a specific repo and wait for completion.

    Authentication: requires a GitHub Actions OIDC JWT in the Authorization header
    (``Authorization: Bearer <token>``).  The ``repository`` claim inside the token
    must match ``body.repo``, so only a workflow running inside that repo can trigger
    a refresh for it.  No user-configured secrets are needed — the OIDC token is
    minted automatically by GitHub Actions.
    """
    from src.event_processors.expertise_scheduler import refresh_expertise_by_repo_name

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        await verify_github_oidc_token(token, expected_repository=body.repo)
    except OIDCVerificationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        await refresh_expertise_by_repo_name(body.repo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Expertise refresh failed for {body.repo}: {exc}",
        ) from exc

    return {"status": "completed", "message": f"Expertise refresh completed for {body.repo}."}
