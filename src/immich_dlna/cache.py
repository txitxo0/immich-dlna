from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class _CachedValue(Generic[T]):
    expires_at: datetime
    value: T


class TtlCache(Generic[T]):
    def __init__(self, ttl_seconds: int, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be > 0")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_size = max_size
        self._values: OrderedDict[str, _CachedValue[T]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> T | None:
        item = self._values.get(key)
        if item is None:
            self._misses += 1
            return None
        now = datetime.now(timezone.utc)
        if item.expires_at <= now:
            del self._values[key]
            self._misses += 1
            return None
        self._hits += 1
        self._values.move_to_end(key)
        return item.value

    def set(self, key: str, value: T) -> None:
        self._values[key] = _CachedValue(
            expires_at=datetime.now(timezone.utc) + self._ttl,
            value=value,
        )
        self._values.move_to_end(key)
        if len(self._values) > self._max_size:
            self._values.popitem(last=False)

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses
