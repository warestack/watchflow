#!/usr/bin/env python3
"""
Tests for caching strategy and configuration.

This test suite verifies that:
1. Cache configuration is properly loaded from environment variables
2. Cache TTL and size limits are configurable
3. Cache respects enable/disable settings
4. Cache eviction policy (LRU) works correctly
5. Cache expiration works as expected
6. Global cache uses config values
7. Function-level cache decorator respects config

Can be run in two ways:
1. As pytest test: pytest tests/feedback/test_caching_strategy.py -v
2. As standalone verification: python3 tests/feedback/test_caching_strategy.py
"""

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path for imports when running directly
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestCacheConfig:
    """Test cache configuration loading."""

    def test_cache_config_defaults(self):
        """Test that CacheConfig has sensible defaults."""
        from src.core.config.cache_config import CacheConfig

        config = CacheConfig()
        assert config.global_maxsize == 1024
        assert config.global_ttl == 3600
        assert config.default_maxsize == 100
        assert config.default_ttl == 3600
        assert config.enable_cache is True
        assert config.enable_metrics is False

    def test_cache_config_from_env(self):
        """Test that cache config loads from environment variables."""
        from src.core.config.settings import Config

        with patch.dict(
            os.environ,
            {
                "CACHE_GLOBAL_MAXSIZE": "2048",
                "CACHE_GLOBAL_TTL": "7200",
                "CACHE_DEFAULT_MAXSIZE": "200",
                "CACHE_DEFAULT_TTL": "1800",
                "CACHE_ENABLE": "false",
                "CACHE_ENABLE_METRICS": "true",
            },
        ):
            # Reload config to pick up env vars
            config = Config()
            assert config.cache.global_maxsize == 2048
            assert config.cache.global_ttl == 7200
            assert config.cache.default_maxsize == 200
            assert config.cache.default_ttl == 1800
            assert config.cache.enable_cache is False
            assert config.cache.enable_metrics is True

    def test_cache_config_in_main_config(self):
        """Test that cache config is included in main Config class."""
        from src.core.config.settings import Config

        config = Config()
        assert hasattr(config, "cache")
        assert config.cache is not None
        assert hasattr(config.cache, "global_maxsize")
        assert hasattr(config.cache, "global_ttl")
        assert hasattr(config.cache, "default_maxsize")
        assert hasattr(config.cache, "default_ttl")
        assert hasattr(config.cache, "enable_cache")
        assert hasattr(config.cache, "enable_metrics")


class TestAsyncCache:
    """Test AsyncCache class functionality."""

    def test_cache_initialization(self):
        """Test cache initialization with custom values."""
        from src.core.utils.caching import AsyncCache

        cache = AsyncCache(maxsize=50, ttl=300)
        assert cache.maxsize == 50
        assert cache.ttl == 300
        assert cache.size() == 0

    def test_cache_set_and_get(self):
        """Test basic cache set and get operations."""
        from src.core.utils.caching import AsyncCache

        cache = AsyncCache(maxsize=10, ttl=3600)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        assert cache.size() == 1

    def test_cache_expiration(self):
        """Test that cache entries expire after TTL."""
        from src.core.utils.caching import AsyncCache

        cache = AsyncCache(maxsize=10, ttl=1)  # 1 second TTL
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Wait for expiration
        time.sleep(1.1)
        assert cache.get("key1") is None
        assert cache.size() == 0

    def test_cache_lru_eviction(self):
        """Test that cache evicts oldest entries when full (LRU policy)."""
        from src.core.utils.caching import AsyncCache

        cache = AsyncCache(maxsize=3, ttl=3600)
        # Fill cache to capacity
        cache.set("key1", "value1")
        time.sleep(0.01)  # Small delay to ensure different timestamps
        cache.set("key2", "value2")
        time.sleep(0.01)
        cache.set("key3", "value3")
        assert cache.size() == 3

        # Add one more - should evict oldest (key1)
        time.sleep(0.01)
        cache.set("key4", "value4")
        assert cache.size() == 3
        assert cache.get("key1") is None  # Oldest evicted
        assert cache.get("key2") == "value2"  # Still present
        assert cache.get("key3") == "value3"  # Still present
        assert cache.get("key4") == "value4"  # Newest present

    def test_cache_clear(self):
        """Test clearing all cache entries."""
        from src.core.utils.caching import AsyncCache

        cache = AsyncCache(maxsize=10, ttl=3600)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        assert cache.size() == 2

        cache.clear()
        assert cache.size() == 0
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_cache_invalidate(self):
        """Test invalidating a specific cache entry."""
        from src.core.utils.caching import AsyncCache

        cache = AsyncCache(maxsize=10, ttl=3600)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        assert cache.size() == 2

        cache.invalidate("key1")
        assert cache.size() == 1
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"

    def test_cache_size_tracking(self):
        """Test that cache correctly tracks size."""
        from src.core.utils.caching import AsyncCache

        cache = AsyncCache(maxsize=5, ttl=3600)
        assert cache.size() == 0

        for i in range(3):
            cache.set(f"key{i}", f"value{i}")
        assert cache.size() == 3

        cache.invalidate("key1")
        assert cache.size() == 2


class TestGlobalCache:
    """Test global module-level cache functionality."""

    @pytest.mark.asyncio
    async def test_global_cache_uses_config(self):
        """Test that global cache uses config values."""
        # Reset global cache to force re-initialization
        import src.core.utils.caching as caching_module
        from src.core.utils.caching import _get_global_cache

        caching_module._GLOBAL_CACHE = None

        with patch("src.core.utils.caching._get_config") as mock_get_config:
            mock_config = MagicMock()
            mock_config.cache.global_maxsize = 512
            mock_config.cache.global_ttl = 1800
            mock_config.cache.enable_cache = True
            mock_get_config.return_value = mock_config

            cache = _get_global_cache()
            assert cache.maxsize == 512
            assert cache.ttl == 1800

    @pytest.mark.asyncio
    async def test_get_cache_respects_enable_flag(self):
        """Test that get_cache respects CACHE_ENABLE setting."""
        # Reset global cache
        import src.core.utils.caching as caching_module
        from src.core.utils.caching import get_cache

        caching_module._GLOBAL_CACHE = None

        with patch("src.core.utils.caching._get_config") as mock_get_config:
            mock_config = MagicMock()
            mock_config.cache.enable_cache = False
            mock_get_config.return_value = mock_config

            # Should return None when cache is disabled
            result = await get_cache("test_key")
            assert result is None

    @pytest.mark.asyncio
    async def test_set_cache_respects_enable_flag(self):
        """Test that set_cache respects CACHE_ENABLE setting."""
        # Reset global cache
        import src.core.utils.caching as caching_module
        from src.core.utils.caching import get_cache, set_cache

        caching_module._GLOBAL_CACHE = None

        with patch("src.core.utils.caching._get_config") as mock_get_config:
            mock_config = MagicMock()
            mock_config.cache.enable_cache = False
            mock_get_config.return_value = mock_config

            # Should be no-op when cache is disabled
            await set_cache("test_key", "test_value")
            result = await get_cache("test_key")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_cache_and_set_cache_integration(self):
        """Test integration of get_cache and set_cache."""
        # Reset global cache
        import src.core.utils.caching as caching_module
        from src.core.utils.caching import get_cache, set_cache

        caching_module._GLOBAL_CACHE = None

        with patch("src.core.utils.caching._get_config") as mock_get_config:
            mock_config = MagicMock()
            mock_config.cache.global_maxsize = 100
            mock_config.cache.global_ttl = 3600
            mock_config.cache.enable_cache = True
            mock_get_config.return_value = mock_config

            # Set and get value
            await set_cache("test_key", "test_value")
            result = await get_cache("test_key")
            assert result == "test_value"

    @pytest.mark.asyncio
    async def test_set_cache_ttl_override(self):
        """Test that set_cache can override TTL."""
        # Reset global cache
        import src.core.utils.caching as caching_module
        from src.core.utils.caching import _get_global_cache, set_cache

        caching_module._GLOBAL_CACHE = None

        with patch("src.core.utils.caching._get_config") as mock_get_config:
            mock_config = MagicMock()
            mock_config.cache.global_maxsize = 100
            mock_config.cache.global_ttl = 3600
            mock_config.cache.enable_cache = True
            mock_get_config.return_value = mock_config

            cache = _get_global_cache()
            assert cache.ttl == 3600

            # Override TTL
            await set_cache("test_key", "test_value", ttl=1800)
            assert cache.ttl == 1800


class TestCachedAsyncDecorator:
    """Test @cached_async decorator functionality."""

    @pytest.mark.asyncio
    async def test_cached_async_basic(self):
        """Test basic caching with @cached_async decorator."""
        from src.core.utils.caching import cached_async

        call_count = 0

        @cached_async(ttl=3600, maxsize=10)
        async def test_func(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        # First call - cache miss
        result1 = await test_func(5)
        assert result1 == 10
        assert call_count == 1

        # Second call - cache hit
        result2 = await test_func(5)
        assert result2 == 10
        assert call_count == 1  # Not called again

    @pytest.mark.asyncio
    async def test_cached_async_uses_config_defaults(self):
        """Test that @cached_async uses config defaults when not specified."""
        from src.core.utils.caching import cached_async

        with patch("src.core.utils.caching._get_config") as mock_get_config:
            mock_config = MagicMock()
            mock_config.cache.default_maxsize = 50
            mock_config.cache.default_ttl = 1800
            mock_config.cache.enable_cache = True
            mock_get_config.return_value = mock_config

            call_count = 0

            @cached_async()  # No parameters - should use config defaults
            async def test_func(x: int) -> int:
                nonlocal call_count
                call_count += 1
                return x * 2

            result = await test_func(5)
            assert result == 10
            assert call_count == 1

    @pytest.mark.asyncio
    async def test_cached_async_respects_enable_flag(self):
        """Test that @cached_async respects CACHE_ENABLE setting."""
        from src.core.utils.caching import cached_async

        with patch("src.core.utils.caching._get_config") as mock_get_config:
            mock_config = MagicMock()
            mock_config.cache.default_maxsize = 50
            mock_config.cache.default_ttl = 1800
            mock_config.cache.enable_cache = False  # Cache disabled
            mock_get_config.return_value = mock_config

            call_count = 0

            @cached_async()
            async def test_func(x: int) -> int:
                nonlocal call_count
                call_count += 1
                return x * 2

            # Both calls should execute (cache disabled)
            result1 = await test_func(5)
            result2 = await test_func(5)
            assert result1 == 10
            assert result2 == 10
            assert call_count == 2  # Called twice because cache is disabled

    @pytest.mark.asyncio
    async def test_cached_async_custom_key_func(self):
        """Test @cached_async with custom key function."""
        from src.core.utils.caching import cached_async

        call_count = 0

        def key_func(x: int, y: int) -> str:
            return f"custom:{x}:{y}"

        @cached_async(ttl=3600, key_func=key_func)
        async def test_func(x: int, y: int) -> int:
            nonlocal call_count
            call_count += 1
            return x + y

        # First call
        result1 = await test_func(5, 3)
        assert result1 == 8
        assert call_count == 1

        # Second call with same args - cache hit
        result2 = await test_func(5, 3)
        assert result2 == 8
        assert call_count == 1

        # Different args - cache miss
        result3 = await test_func(5, 4)
        assert result3 == 9
        assert call_count == 2


class TestCacheDocumentation:
    """Test that caching strategy is properly documented."""

    def test_caching_module_has_documentation(self):
        """Test that caching.py has comprehensive documentation."""
        caching_file = ROOT / "src" / "core" / "utils" / "caching.py"
        assert caching_file.exists()

        content = caching_file.read_text()

        # Check for key documentation sections
        assert "Caching Strategy" in content
        assert "TTL" in content or "Time To Live" in content
        assert "Eviction Policy" in content or "LRU" in content
        assert "Configuration" in content
        assert "Environment variables" in content or "CACHE_" in content

    def test_cache_config_has_docstrings(self):
        """Test that CacheConfig has proper docstrings."""
        from src.core.config.cache_config import CacheConfig

        assert CacheConfig.__doc__ is not None
        assert len(CacheConfig.__doc__.strip()) > 0


def run_standalone_verification():
    """Run verification checks that don't require pytest."""
    print("=" * 60)
    print("Caching Strategy Verification")
    print("=" * 60)
    print()

    all_passed = True

    # Test 1: Config exists
    print("1. Checking CacheConfig exists...")
    try:
        from src.core.config.cache_config import CacheConfig

        config = CacheConfig()
        print("   ✅ CacheConfig created with defaults")
        print(f"      - global_maxsize: {config.global_maxsize}")
        print(f"      - global_ttl: {config.global_ttl}")
        print(f"      - default_maxsize: {config.default_maxsize}")
        print(f"      - default_ttl: {config.default_ttl}")
        print(f"      - enable_cache: {config.enable_cache}")
    except Exception as e:
        print(f"   ❌ Failed to import CacheConfig: {e}")
        all_passed = False

    # Test 2: Config in main settings
    print()
    print("2. Checking CacheConfig in main Config...")
    try:
        from src.core.config.settings import Config

        config = Config()
        assert hasattr(config, "cache")
        print("   ✅ CacheConfig included in main Config")
        print(f"      - config.cache.global_maxsize: {config.cache.global_maxsize}")
    except Exception as e:
        print(f"   ❌ Failed to access cache config: {e}")
        all_passed = False

    # Test 3: AsyncCache works
    print()
    print("3. Checking AsyncCache functionality...")
    try:
        from src.core.utils.caching import AsyncCache

        cache = AsyncCache(maxsize=5, ttl=1)
        cache.set("test", "value")
        assert cache.get("test") == "value"
        assert cache.size() == 1
        print("   ✅ AsyncCache basic operations work")
    except Exception as e:
        print(f"   ❌ AsyncCache test failed: {e}")
        all_passed = False

    # Test 4: Documentation exists
    print()
    print("4. Checking documentation...")
    caching_file = ROOT / "src" / "core" / "utils" / "caching.py"
    if caching_file.exists():
        content = caching_file.read_text()
        if "Caching Strategy" in content:
            print("   ✅ Caching strategy documentation found")
        else:
            print("   ⚠️  Caching strategy documentation may be incomplete")
    else:
        print("   ❌ Caching file not found")
        all_passed = False

    print()
    print("=" * 60)
    if all_passed:
        print("✅ All verification checks passed!")
    else:
        print("❌ Some checks failed")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    # Run standalone verification when executed directly
    success = run_standalone_verification()
    sys.exit(0 if success else 1)
