from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

class MetricsRegistry:
    def __init__(self, connected_device_ttl_seconds: int) -> None:
        self._app_name = "immich-dlna"
        buckets = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
        self._registry = CollectorRegistry(auto_describe=True)
        self._requests_duration = Histogram(
            name="requests_duration_seconds",
            documentation="Duration of incoming HTTP requests in seconds.",
            labelnames=("app", "method", "route", "status"),
            buckets=buckets,
            registry=self._registry,
        )
        self._outgoing_duration = Histogram(
            name="outgoing_requests_duration_seconds",
            documentation="Duration of outgoing Immich API requests in seconds.",
            labelnames=("app", "method", "target", "status"),
            buckets=buckets,
            registry=self._registry,
        )
        self._errors_total = Counter(
            name="errors_total",
            documentation="Total number of internal errors.",
            labelnames=("app", "source"),
            registry=self._registry,
        )
        self._connected_devices = Gauge(
            name="connected_devices",
            documentation="Number of recently seen SSDP clients.",
            labelnames=("app",),
            registry=self._registry,
        )
        self._cache_hit_ratio = Gauge(
            name="cache_hit_ratio",
            documentation="Ratio of cache hits to all cache lookups.",
            labelnames=("app",),
            registry=self._registry,
        )
        self._connected_devices_last_seen: dict[str, float] = {}
        self._connected_device_ttl = float(max(connected_device_ttl_seconds, 1))
        self._content_type = CONTENT_TYPE_LATEST

    def observe_request(self, method: str, route: str, status: int, duration_seconds: float) -> None:
        self._requests_duration.labels(
            app=self._app_name,
            method=method,
            route=route,
            status=str(status),
        ).observe(duration_seconds)

    def observe_outgoing(self, method: str, target: str, status: str, duration_seconds: float) -> None:
        self._outgoing_duration.labels(
            app=self._app_name,
            method=method,
            target=target,
            status=status,
        ).observe(duration_seconds)

    def increment_error(self, source: str) -> None:
        self._errors_total.labels(app=self._app_name, source=source).inc()

    def mark_device_seen(self, ip_address: str) -> None:
        if not ip_address:
            return
        self._connected_devices_last_seen[ip_address] = time.monotonic()

    def connected_devices_count(self) -> int:
        now = time.monotonic()
        stale_before = now - self._connected_device_ttl
        stale = [ip for ip, last_seen in self._connected_devices_last_seen.items() if last_seen < stale_before]
        for ip in stale:
            del self._connected_devices_last_seen[ip]
        return len(self._connected_devices_last_seen)

    @property
    def content_type(self) -> str:
        return self._content_type

    def render_prometheus(self, cache_hit_ratio: float) -> bytes:
        self._connected_devices.labels(app=self._app_name).set(self.connected_devices_count())
        self._cache_hit_ratio.labels(app=self._app_name).set(cache_hit_ratio)
        return generate_latest(self._registry)
