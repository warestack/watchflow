"""
Cache configuration.

Defines configurable settings for caching strategy including TTL, size limits,
and cache behavior.
"""

from dataclasses import dataclass


@dataclass
class CacheConfig:
    """Cache configuration."""

    # Global cache settings (used by recommendations API and other module-level caches)
    global_maxsize: int = 1024
    global_ttl: int = 3600  # 1 hour in seconds

    # Default cache settings for new AsyncCache instances
    default_maxsize: int = 100
    default_ttl: int = 3600  # 1 hour in seconds

    # Cache behavior settings
    enable_cache: bool = True  # Master switch to disable all caching
    enable_metrics: bool = False  # Track cache hit/miss rates (future feature)
