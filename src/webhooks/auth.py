import hashlib
import hmac
import logging

from fastapi import HTTPException, Request

from src.core.config import config

logger = logging.getLogger(__name__)

GITHUB_WEBHOOK_SECRET = config.github.webhook_secret


async def verify_github_signature(request: Request) -> bool:
    """
    FastAPI dependency that verifies the GitHub webhook signature.

    This function reads the 'X-Hub-Signature-256' header and compares it
    with a hash of the raw request body, using our configured webhook secret.

    Raises:
        HTTPException: If the signature is missing or invalid.

    Returns:
        True if the signature is valid.
    """
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        logger.warning("Received a request without the X-Hub-Signature-256 header.")
        raise HTTPException(status_code=401, detail="Missing GitHub webhook signature.")

    # Get the raw request payload  as bytes
    payload = await request.body()

    # Calculate the expected signature
    mac = hmac.new(GITHUB_WEBHOOK_SECRET.encode(), msg=payload, digestmod=hashlib.sha256)
    expected_signature = f"sha256={mac.hexdigest()}"

    # Securely compare the signatures
    if not hmac.compare_digest(signature, expected_signature):
        logger.error("Invalid webhook signature.")
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature.")

    logger.debug("GitHub webhook signature verified successfully.")
    return True
