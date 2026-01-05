"""
Caching utilities for async operations.

Provides async-friendly caching with TTL support and decorators
for caching function results.

"""

import logging
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from typing import Any

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependency
_config: Any = None


def _get_config():
    """Lazy load config to avoid circular dependencies."""
    global _config
    if _config is None:
        from src.core.config.settings import config

        _config = config
    return _config


class AsyncCache:
    """
    Async-friendly cache with TTL support.

    This cache stores values with timestamps and automatically
    expires entries based on TTL.

    Example:
        cache = AsyncCache(maxsize=100, ttl=3600)
        cache.set("key", "value")
        value = cache.get("key")
    """

    def __init__(self, maxsize: int = 100, ttl: int = 3600):
        """
        Initialize async cache.

        Args:
            maxsize: Maximum number of entries in cache
            ttl: Time to live in seconds
        """
        self._cache: dict[str, dict[str, Any]] = {}
        self.maxsize = maxsize
        self.ttl = ttl

    def get(self, key: str) -> Any | None:
        """
        Get cached value if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found or expired

        Note:
            Expired entries are removed lazily (on access) to avoid
            background cleanup overhead.
        """
        if key not in self._cache:
            return None

        cached_data = self._cache[key]
        age = datetime.now().timestamp() - cached_data.get("timestamp", 0)

        if age >= self.ttl:
            del self._cache[key]
            logger.debug(f"Cache entry '{key}' expired (age: {age:.2f}s, ttl: {self.ttl}s)")
            return None

        logger.debug(f"Cache hit for '{key}'")
        return cached_data.get("value")

    def set(self, key: str, value: Any) -> None:
        """
        Set cached value with timestamp.

        Args:
            key: Cache key
            value: Value to cache

        Note:
            Uses LRU (Least Recently Used) eviction policy when cache is full.
            The oldest entry (by timestamp) is removed to make room.
        """
        if len(self._cache) >= self.maxsize:
            # Remove oldest entry (LRU eviction)
            oldest_key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].get("timestamp", 0),
            )
            logger.debug(f"Cache full, evicting oldest entry '{oldest_key}'")
            del self._cache[oldest_key]

        self._cache[key] = {
            "value": value,
            "timestamp": datetime.now().timestamp(),
        }
        logger.debug(f"Cached entry '{key}'")

    def clear(self) -> None:
        """Clear all cached values."""
        count = len(self._cache)
        self._cache.clear()
        logger.debug(f"Cleared {count} cache entries")

    def invalidate(self, key: str) -> None:
        """
        Invalidate a specific cache entry.

        Args:
            key: Cache key to invalidate
        """
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Invalidated cache entry '{key}'")

    def size(self) -> int:
        """
        Get current cache size.

        Returns:
            Number of entries in cache
        """
        return len(self._cache)


# Global module-level cache used by recommendations API and other shared operations
# Initialized lazily with config values to avoid circular dependencies
_GLOBAL_CACHE: AsyncCache | None = None


def _get_global_cache() -> AsyncCache:
    """
    Get or initialize the global cache with config values.

    Returns:
        Global AsyncCache instance configured from settings
    """
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        config = _get_config()
        _GLOBAL_CACHE = AsyncCache(
            maxsize=config.cache.global_maxsize,
            ttl=config.cache.global_ttl,
        )
    return _GLOBAL_CACHE


async def get_cache(key: str) -> Any | None:
    """
    Async helper to fetch from the module-level cache.

    Args:
        key: Cache key to retrieve

    Returns:
        Cached value or None if not found, expired, or caching disabled

    Note:
        Respects CACHE_ENABLE setting - returns None if caching is disabled.
    """
    config = _get_config()
    if not config.cache.enable_cache:
        return None
    return _get_global_cache().get(key)


async def set_cache(key: str, value: Any, ttl: int | None = None) -> None:
    """
    Async helper to store into the module-level cache.

    Args:
        key: Cache key
        value: Value to cache
        ttl: Optional TTL override (applies to entire cache, not just this entry)

    Note:
        Respects CACHE_ENABLE setting - no-op if caching is disabled.
        If ttl is provided, it updates the cache's TTL for all entries.
        Individual entry TTL is not supported; all entries share the cache TTL.
    """
    config = _get_config()
    if not config.cache.enable_cache:
        return

    cache = _get_global_cache()
    if ttl and ttl != cache.ttl:
        # Update cache TTL (affects all entries)
        cache.ttl = ttl
        logger.debug(f"Updated global cache TTL to {ttl}s")
    cache.set(key, value)


def cached_async(
    cache: AsyncCache | TTLCache | None = None,
    key_func: Callable[..., str] | None = None,
    ttl: int | None = None,
    maxsize: int | None = None,
):
    """
    Decorator for caching async function results.

    Args:
        cache: Cache instance to use (creates new AsyncCache if None)
        key_func: Function to generate cache key from function arguments
        ttl: Time to live in seconds (only used if cache is None)
        maxsize: Maximum cache size (only used if cache is None, defaults to config)

    Returns:
        Decorated async function with caching

    Example:
        @cached_async(ttl=3600, key_func=lambda repo, *args: f"repo:{repo}")
        async def fetch_repo_data(repo: str):
            return await api_call(repo)

    Note:
        Respects CACHE_ENABLE setting - bypasses cache if disabled.
        Uses config defaults for ttl and maxsize if not provided.
    """
    if cache is None:
        config = _get_config()
        # Use provided values or fall back to config defaults
        cache_ttl = ttl if ttl is not None else config.cache.default_ttl
        cache_maxsize = maxsize if maxsize is not None else config.cache.default_maxsize
        cache = AsyncCache(maxsize=cache_maxsize, ttl=cache_ttl)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            config = _get_config()
            # Bypass cache if disabled
            if not config.cache.enable_cache:
                return await func(*args, **kwargs)

            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Default: use function name and arguments
                cache_key = f"{func.__name__}:{args}:{kwargs}"

            # Check cache
            if isinstance(cache, AsyncCache):
                cached_value = cache.get(cache_key)
            else:
                # TTLCache
                cached_value = cache.get(cache_key)

            if cached_value is not None:
                logger.debug(f"Cache hit for {func.__name__} with key '{cache_key}'")
                return cached_value

            # Cache miss - execute function
            logger.debug(f"Cache miss for {func.__name__} with key '{cache_key}'")
            result = await func(*args, **kwargs)

            # Store in cache
            if isinstance(cache, AsyncCache):
                cache.set(cache_key, result)
            else:
                # TTLCache
                cache[cache_key] = result

            return result

        return wrapper

    return decorator
