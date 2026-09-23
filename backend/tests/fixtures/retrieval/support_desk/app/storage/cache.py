"""An in-process cache that discards the least recently used entries when full."""

from collections import OrderedDict
from typing import Any


class LruCache:
    """Fixed-capacity cache; the oldest untouched entry is evicted first."""

    def __init__(self, capacity: int = 128) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._entries: OrderedDict[str, Any] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        if key not in self._entries:
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return self._entries[key]

    def put(self, key: str, value: Any) -> None:
        """Store a value, evicting the least recently used entry if the cache is full."""
        if key in self._entries:
            self._entries.move_to_end(key)
        self._entries[key] = value
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)
