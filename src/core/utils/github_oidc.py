"""
GitHub Actions OIDC token verification.

GitHub Actions can mint short-lived JWTs signed by GitHub's private key.
This module verifies those tokens so the refresh-expertise endpoint can
authenticate callers without any user-configured secrets.

Verification steps:
  1. Fetch GitHub's JWKS from the well-known URL (cached for 1 h).
  2. Decode and verify the JWT signature against the matching key.
  3. Check standard claims: iss, exp, and the caller-supplied repository.

Reference: https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/about-security-hardening-with-openid-connect
"""

import asyncio
import logging
from functools import partial
from typing import Any

import jwt
from jwt import PyJWKClient, PyJWKClientError

logger = logging.getLogger(__name__)

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
_JWKS_URL = f"{GITHUB_OIDC_ISSUER}/.well-known/jwks"
_AUDIENCE = "watchflow"

# Module-level JWKS client — caches keys internally (lifespan of the process)
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(_JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwks_client


class OIDCVerificationError(Exception):
    """Raised when an OIDC token fails verification."""


def _verify_sync(token: str, expected_repository: str) -> dict[str, Any]:
    """Synchronous verification — run this in a thread via ``verify_github_oidc_token``.

    Separated so the blocking JWKS network call and CPU-bound JWT crypto never
    run on the event loop thread directly.
    """
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
    except PyJWKClientError as exc:
        raise OIDCVerificationError(f"Failed to fetch signing key: {exc}") from exc
    except Exception as exc:
        raise OIDCVerificationError(f"JWKS lookup failed: {exc}") from exc

    # Use signing_key.key (the raw cryptographic key) to avoid PyJWT version
    # differences where passing the PyJWK wrapper object directly raises a
    # key-format/type error.
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=GITHUB_OIDC_ISSUER,
            audience=_AUDIENCE,
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError as exc:
        raise OIDCVerificationError("Token has expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise OIDCVerificationError(f"Invalid audience (expected '{_AUDIENCE}')") from exc
    except jwt.InvalidIssuerError as exc:
        raise OIDCVerificationError(f"Invalid issuer (expected '{GITHUB_OIDC_ISSUER}')") from exc
    except jwt.PyJWTError as exc:
        raise OIDCVerificationError(f"Token verification failed: {exc}") from exc

    token_repo = claims.get("repository", "")
    if token_repo != expected_repository:
        raise OIDCVerificationError(
            f"Token repository '{token_repo}' does not match requested repository '{expected_repository}'"
        )

    logger.debug(
        "OIDC token verified for %s (workflow: %s, ref: %s)",
        token_repo,
        claims.get("workflow"),
        claims.get("ref"),
    )
    return claims


async def verify_github_oidc_token(token: str, expected_repository: str) -> dict[str, Any]:
    """Verify a GitHub Actions OIDC JWT and return its claims.

    Runs the blocking JWKS fetch and JWT verification in a thread pool so the
    event loop is not stalled under concurrent requests.

    Args:
        token: Raw JWT string from the Authorization header.
        expected_repository: The ``owner/repo`` the caller claims to be.
            The ``repository`` claim inside the token must match exactly.

    Returns:
        Decoded claims dict on success.

    Raises:
        OIDCVerificationError: If the token is invalid, expired, or does not
            match the expected repository.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_verify_sync, token, expected_repository))
