import logging

from fastapi import Depends, HTTPException, Request, status

from src.core.models import User
from src.integrations.github.service import GitHubService

logger = logging.getLogger(__name__)  # Logger: keep at module level for reuse.
logger = logging.getLogger(__name__)

# --- Service Dependencies ---  # DI: swap for mock in tests.


def get_github_service() -> GitHubService:
    """
    Injects GitHubService—future: allow mock for integration tests.
    """
    return GitHubService()


# --- Auth Dependencies ---  # Auth: allow anonymous for public repo support.


async def get_current_user_optional(request: Request) -> User | None:
    """
    Auth check—don't fail if missing. Critical for public repo support (Phase 1).
    """
    auth_header = request.headers.get("Authorization")

    if not auth_header:
        return None

    try:
        # Token extraction—fragile if header format changes.
        scheme, token = auth_header.split()
        if scheme.lower() != "bearer":
            return None

        # TODO: Wire to real IdP (Supabase/Auth0). For now, fake user if token present. WARNING: Must verify signature in prod.
        return User(id=123, username="authenticated_user", email="user@example.com", github_token=token)
    except Exception as e:
        logger.warning(f"Failed to parse auth header: {e}")
        return None


async def get_current_user(user: User | None = Depends(get_current_user_optional)) -> User:
    """
    Strict dependency for endpoints that MUST have a user (e.g., 'Analyze Private Repo').
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required for this operation."
        )
    return user
