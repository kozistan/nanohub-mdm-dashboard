"""
NanoHUB Cache Utilities
=======================
In-memory cache for processed device data to reduce JSON parsing overhead.

Usage:
    from cache_utils import device_cache

    # Get cached processed data
    data = device_cache.get(uuid)

    # Set processed data
    device_cache.set(uuid, processed_data)

    # Invalidate on update
    device_cache.invalidate(uuid)

    # Clear all
    device_cache.clear()
"""

import time
import threading
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger('nanohub_cache')


class DeviceCache:
    """Thread-safe in-memory cache for processed device data."""

    def __init__(self, default_ttl: int = 60, max_size: int = 2000):
        """
        Initialize cache.

        Args:
            default_ttl: Default time-to-live in seconds (60s default)
            max_size: Maximum number of entries (prevents memory bloat)
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    def get(self, uuid: str) -> Optional[Dict[str, Any]]:
        """
        Get cached data for device.

        Args:
            uuid: Device UUID

        Returns:
            Cached data dict or None if not found/expired
        """
        with self._lock:
            entry = self._cache.get(uuid)
            if entry is None:
                self._misses += 1
                return None

            # Check expiry
            if time.time() > entry['expires_at']:
                del self._cache[uuid]
                self._misses += 1
                return None

            self._hits += 1
            return entry['data']

    def set(self, uuid: str, data: Dict[str, Any], ttl: int = None) -> None:
        """
        Cache processed data for device.

        Args:
            uuid: Device UUID
            data: Processed data dict
            ttl: Optional custom TTL in seconds
        """
        with self._lock:
            # Evict oldest entries if at max size
            if len(self._cache) >= self._max_size:
                self._evict_oldest(count=self._max_size // 10)

            self._cache[uuid] = {
                'data': data,
                'expires_at': time.time() + (ttl or self._default_ttl),
                'created_at': time.time()
            }

    def invalidate(self, uuid: str) -> bool:
        """
        Remove device from cache (call after device_details update).

        Args:
            uuid: Device UUID

        Returns:
            True if entry was removed, False if not found
        """
        with self._lock:
            if uuid in self._cache:
                del self._cache[uuid]
                logger.debug(f"Cache invalidated for {uuid[:8]}...")
                return True
            return False

    def invalidate_all(self) -> int:
        """
        Clear entire cache.

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cache cleared: {count} entries")
            return count

    def clear(self) -> int:
        """Alias for invalidate_all()."""
        return self.invalidate_all()

    def _evict_oldest(self, count: int = 100) -> None:
        """Remove oldest entries from cache."""
        if not self._cache:
            return

        # Sort by created_at and remove oldest
        sorted_keys = sorted(
            self._cache.keys(),
            key=lambda k: self._cache[k].get('created_at', 0)
        )

        for key in sorted_keys[:count]:
            del self._cache[key]

        logger.debug(f"Evicted {count} oldest cache entries")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0

            return {
                'size': len(self._cache),
                'max_size': self._max_size,
                'ttl': self._default_ttl,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': f"{hit_rate:.1f}%"
            }

    def get_multi(self, uuids: list) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Get cached data for multiple devices.

        Args:
            uuids: List of device UUIDs

        Returns:
            Dict mapping uuid -> cached data (or None if not cached)
        """
        result = {}
        for uuid in uuids:
            result[uuid] = self.get(uuid)
        return result

    def set_multi(self, data_dict: Dict[str, Dict[str, Any]], ttl: int = None) -> None:
        """
        Cache data for multiple devices.

        Args:
            data_dict: Dict mapping uuid -> processed data
            ttl: Optional custom TTL
        """
        for uuid, data in data_dict.items():
            self.set(uuid, data, ttl)


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

# Global cache instance (60 second TTL, max 2000 devices)
device_cache = DeviceCache(default_ttl=60, max_size=2000)
