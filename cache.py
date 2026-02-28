"""Response caching for MyClaw.

Provides caching for upstream responses with TTL and invalidation.
"""

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("myclaw.cache")


@dataclass
class CacheEntry:
    """Cache entry with metadata."""

    key: str
    value: Any
    created_at: float
    ttl: int
    hits: int = 0

    def is_expired(self) -> bool:
        """Check if entry is expired."""
        return time.time() - self.created_at > self.ttl


class ResponseCache:
    """In-memory response cache with TTL and invalidation."""

    def __init__(
        self,
        default_ttl: int = 300,
        max_entries: int = 1000,
    ):
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        self._cache: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def _generate_key(self, data: dict) -> str:
        """Generate cache key from request data."""
        normalized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(normalized.encode()).hexdigest()[:32]

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                return None

            entry.hits += 1
            self._hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl: int = None) -> None:
        """Set value in cache."""
        with self._lock:
            if len(self._cache) >= self.max_entries:
                self._evict_oldest()

            self._cache[key] = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                ttl=ttl or self.default_ttl,
            )

    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys matching a pattern."""
        with self._lock:
            to_delete = [k for k in self._cache.keys() if pattern in k]
            for key in to_delete:
                del self._cache[key]
            return len(to_delete)

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def _evict_oldest(self) -> None:
        """Evict the oldest entry."""
        if not self._cache:
            return

        oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].created_at)
        del self._cache[oldest_key]

    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0

            return {
                "entries": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 2),
                "max_entries": self.max_entries,
            }

    def cleanup_expired(self) -> int:
        """Remove expired entries."""
        with self._lock:
            expired = [k for k, v in self._cache.items() if v.is_expired()]
            for key in expired:
                del self._cache[key]
            return len(expired)


_cache: Optional[ResponseCache] = None


def get_cache(
    default_ttl: int = 300,
    max_entries: int = 1000,
) -> ResponseCache:
    """Get or create the response cache."""
    global _cache

    if _cache is None:
        _cache = ResponseCache(default_ttl=default_ttl, max_entries=max_entries)

    return _cache


def cache_response(
    key_data: dict,
    response: Any,
    ttl: int = None,
) -> None:
    """Cache a response."""
    cache = get_cache()
    key = cache._generate_key(key_data)
    cache.set(key, response, ttl)


def get_cached_response(key_data: dict) -> Optional[Any]:
    """Get cached response."""
    cache = get_cache()
    key = cache._generate_key(key_data)
    return cache.get(key)


def invalidate_cache(pattern: str = None) -> int:
    """Invalidate cache entries."""
    cache = get_cache()
    if pattern:
        return cache.invalidate_pattern(pattern)
    cache.clear()
    return 0
