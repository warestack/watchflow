"""
Rate limiting dependency for FastAPI endpoints.
Limits requests per IP (anonymous) or user (authenticated).
"""

import time

from fastapi import Depends, HTTPException, Request, status

from src.core.models import User

# In-memory store: { key: [timestamps] }
_RATE_LIMIT_STORE: dict[str, list[float]] = {}

ANON_LIMIT = 5  # requests per hour
AUTH_LIMIT = 100  # requests per hour
WINDOW = 3600  # seconds


async def rate_limiter(request: Request, user: User | None = Depends(lambda: None)):
    now = time.time()
    if user and user.email:
        key = f"user:{user.email}"
        limit = AUTH_LIMIT
    else:
        key = f"ip:{request.client.host}"
        limit = ANON_LIMIT

    timestamps = _RATE_LIMIT_STORE.get(key, [])
    # Remove timestamps outside the window
    timestamps = [ts for ts in timestamps if now - ts < WINDOW]
    if len(timestamps) >= limit:
        retry_after = int(WINDOW - (now - min(timestamps)))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
    timestamps.append(now)
    _RATE_LIMIT_STORE[key] = timestamps
