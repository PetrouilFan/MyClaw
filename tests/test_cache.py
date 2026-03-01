"""Tests for Cache."""

import time

import pytest

from cache import (
    CacheEntry,
    ResponseCache,
    cache_response,
    get_cached_response,
    invalidate_cache,
)


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_create_entry(self):
        """Test creating a cache entry."""
        entry = CacheEntry(key="test", value="data", created_at=time.time(), ttl=60)
        assert entry.key == "test"
        assert entry.value == "data"
        assert entry.ttl == 60

    def test_is_expired(self):
        """Test expiration check."""
        entry = CacheEntry(key="test", value="data", created_at=time.time() - 100, ttl=60)
        assert entry.is_expired() is True

    def test_not_expired(self):
        """Test non-expired entry."""
        entry = CacheEntry(key="test", value="data", created_at=time.time(), ttl=60)
        assert entry.is_expired() is False


class TestResponseCacheInit:
    """Tests for ResponseCache initialization."""

    def test_default_values(self):
        """Test default initialization values."""
        cache = ResponseCache()
        assert cache.default_ttl == 300
        assert cache.max_entries == 1000

    def test_custom_values(self):
        """Test initialization with custom values."""
        cache = ResponseCache(default_ttl=60, max_entries=100)
        assert cache.default_ttl == 60
        assert cache.max_entries == 100


class TestCacheGetSet:
    """Tests for cache get and set methods."""

    def test_set_and_get(self, cache):
        """Test setting and getting a value."""
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_nonexistent(self, cache):
        """Test getting nonexistent key."""
        result = cache.get("nonexistent")
        assert result is None

    def test_get_after_expiry(self, cache):
        """Test getting after TTL expires."""
        cache.set("key1", "value1", ttl=-1)
        time.sleep(0.01)
        result = cache.get("key1")
        assert result is None


class TestCacheDelete:
    """Tests for cache delete method."""

    def test_delete_existing(self, cache):
        """Test deleting existing key."""
        cache.set("key1", "value1")
        result = cache.delete("key1")
        assert result is True
        assert cache.get("key1") is None

    def test_delete_nonexistent(self, cache):
        """Test deleting nonexistent key."""
        result = cache.delete("nonexistent")
        assert result is False


class TestCacheInvalidate:
    """Tests for cache invalidation methods."""

    def test_clear(self, cache):
        """Test clearing all cache entries."""
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_invalidate_pattern(self, cache):
        """Test invalidating by pattern."""
        cache.set("tool_terminal", "value1")
        cache.set("tool_file", "value2")
        cache.set("other_key", "value3")
        count = cache.invalidate_pattern("tool_")
        assert count == 2
        assert cache.get("tool_terminal") is None
        assert cache.get("other_key") == "value3"


class TestCacheStats:
    """Tests for cache statistics."""

    def test_initial_stats(self, cache):
        """Test initial statistics."""
        stats = cache.get_stats()
        assert stats["entries"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_hit_increments(self, cache):
        """Test hit counter increments."""
        cache.set("key1", "value1")
        cache.get("key1")
        cache.get("key1")
        stats = cache.get_stats()
        assert stats["hits"] == 2

    def test_miss_increments(self, cache):
        """Test miss counter increments."""
        cache.get("nonexistent")
        stats = cache.get_stats()
        assert stats["misses"] >= 1

    def test_hit_rate(self, cache):
        """Test hit rate calculation."""
        cache.set("key1", "value1")
        cache.get("key1")
        cache.get("nonexistent")
        stats = cache.get_stats()
        assert stats["hit_rate"] == 50.0


class TestCacheCleanup:
    """Tests for cache cleanup."""

    def test_cleanup_expired(self, cache):
        """Test cleaning up expired entries."""
        cache.set("key1", "value1", ttl=-1)
        time.sleep(0.01)
        count = cache.cleanup_expired()
        assert count >= 1


class TestMaxEntries:
    """Tests for max entries limit."""

    def test_eviction(self, cache):
        """Test that oldest entry is evicted."""
        small_cache = ResponseCache(max_entries=2)
        small_cache.set("key1", "value1")
        time.sleep(0.01)
        small_cache.set("key2", "value2")
        time.sleep(0.01)
        small_cache.set("key3", "value3")
        assert small_cache.get("key1") is None
        assert small_cache.get("key3") == "value3"


class TestGenerateKey:
    """Tests for key generation."""

    def test_generate_key(self, cache):
        """Test key generation is deterministic."""
        key1 = cache._generate_key({"a": 1, "b": 2})
        key2 = cache._generate_key({"b": 2, "a": 1})
        assert key1 == key2

    def test_different_data_different_key(self, cache):
        """Test different data produces different keys."""
        key1 = cache._generate_key({"a": 1})
        key2 = cache._generate_key({"a": 2})
        assert key1 != key2


class TestCacheFunctions:
    """Tests for module-level cache functions."""

    def test_cache_response(self):
        """Test caching a response."""
        cache_response({"prompt": "test"}, {"response": "hello"})
        result = get_cached_response({"prompt": "test"})
        assert result == {"response": "hello"}

    def test_invalidate_cache(self):
        """Test invalidating cache."""
        cache_response({"prompt": "test"}, {"response": "hello"})
        invalidate_cache()
        result = get_cached_response({"prompt": "test"})
        assert result is None


class TestIntegration:
    """Integration tests for cache."""

    def test_full_workflow(self):
        """Test complete cache workflow."""
        cache = ResponseCache(default_ttl=60)

        cache.set("user:1", {"name": "Alice"})
        cache.set("user:2", {"name": "Bob"})

        result1 = cache.get("user:1")
        assert result1 == {"name": "Alice"}

        result2 = cache.get("nonexistent")
        assert result2 is None

        stats = cache.get_stats()
        assert stats["entries"] == 2

        deleted = cache.delete("user:1")
        assert deleted is True

        final_stats = cache.get_stats()
        assert final_stats["entries"] == 1


@pytest.fixture
def cache():
    """Create a fresh cache for each test."""
    return ResponseCache()
