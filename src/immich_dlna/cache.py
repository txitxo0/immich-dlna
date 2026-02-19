from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class _CachedValue(Generic[T]):
    expires_at: datetime
    value: T


class TtlCache(Generic[T]):
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._values: dict[str, _CachedValue[T]] = {}
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
        return item.value

    def set(self, key: str, value: T) -> None:
        self._values[key] = _CachedValue(
            expires_at=datetime.now(timezone.utc) + self._ttl,
            value=value,
        )

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses
