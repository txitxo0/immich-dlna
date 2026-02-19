from __future__ import annotations

from dataclasses import dataclass
import os
import socket
from urllib.parse import urlsplit, urlunsplit
import uuid


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"Environment variable {name} must be an integer, got: {value}") from error


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Environment variable {name} must be a boolean, got: {value}")


def _read_required_str(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Environment variable {name} is required.")
    return value


def _normalize_immich_url(raw_url: str) -> str:
    normalized = raw_url.rstrip("/")
    parsed = urlsplit(normalized)
    if not parsed.scheme or not parsed.netloc:
        return normalized

    path = parsed.path or ""
    if path in {"", "/"}:
        path = "/api"
    else:
        path = path.rstrip("/")

    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _default_base_url(port: int) -> str:
    try:
        host_ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        host_ip = "127.0.0.1"
    return f"http://{host_ip}:{port}"


def _normalize_uuid(value: str | None) -> str:
    if value:
        normalized = value.removeprefix("uuid:")
        return str(uuid.UUID(normalized))
    generated = uuid.uuid5(uuid.NAMESPACE_DNS, f"{socket.gethostname()}-immich-dlna")
    return str(generated)


@dataclass(frozen=True, slots=True)
class Settings:
    http_host: str
    http_port: int
    base_url: str
    friendly_name: str
    server_uuid: str
    log_level: str
    ssdp_multicast_host: str
    ssdp_port: int
    ssdp_max_age: int
    ssdp_notify_interval: int
    immich_url: str
    immich_api_token: str
    immich_verify_ssl: bool
    immich_timeout_seconds: int
    metadata_cache_ttl_seconds: int
    metadata_cache_max_entries: int
    immich_max_concurrent_requests: int

    @classmethod
    def from_env(cls) -> "Settings":
        http_port = _read_int("IMMICH_DLNA_HTTP_PORT", 8200)
        ssdp_max_age = _read_int("IMMICH_DLNA_SSDP_MAX_AGE", 1800)
        ssdp_notify_interval = _read_int("IMMICH_DLNA_SSDP_NOTIFY_INTERVAL", 900)
        immich_timeout_seconds = _read_int("IMMICH_DLNA_IMMICH_TIMEOUT_SECONDS", 20)
        metadata_cache_ttl_seconds = _read_int("IMMICH_DLNA_METADATA_CACHE_TTL_SECONDS", 30)
        metadata_cache_max_entries = _read_int("IMMICH_DLNA_METADATA_CACHE_MAX_ENTRIES", 2000)
        immich_max_concurrent_requests = _read_int("IMMICH_DLNA_IMMICH_MAX_CONCURRENT_REQUESTS", 16)

        if ssdp_notify_interval <= 0:
            raise ValueError("IMMICH_DLNA_SSDP_NOTIFY_INTERVAL must be > 0.")
        if ssdp_max_age <= 0:
            raise ValueError("IMMICH_DLNA_SSDP_MAX_AGE must be > 0.")
        if ssdp_notify_interval > ssdp_max_age:
            raise ValueError(
                "IMMICH_DLNA_SSDP_NOTIFY_INTERVAL must be <= IMMICH_DLNA_SSDP_MAX_AGE."
            )
        if immich_timeout_seconds <= 0:
            raise ValueError("IMMICH_DLNA_IMMICH_TIMEOUT_SECONDS must be > 0.")
        if metadata_cache_ttl_seconds <= 0:
            raise ValueError("IMMICH_DLNA_METADATA_CACHE_TTL_SECONDS must be > 0.")
        if metadata_cache_max_entries <= 0:
            raise ValueError("IMMICH_DLNA_METADATA_CACHE_MAX_ENTRIES must be > 0.")
        if immich_max_concurrent_requests <= 0:
            raise ValueError("IMMICH_DLNA_IMMICH_MAX_CONCURRENT_REQUESTS must be > 0.")

        return cls(
            http_host=os.getenv("IMMICH_DLNA_HTTP_HOST", "0.0.0.0"),
            http_port=http_port,
            base_url=os.getenv("IMMICH_DLNA_BASE_URL", _default_base_url(http_port)).rstrip("/"),
            friendly_name=os.getenv("IMMICH_DLNA_FRIENDLY_NAME", "Immich DLNA"),
            server_uuid=_normalize_uuid(os.getenv("IMMICH_DLNA_SERVER_UUID")),
            log_level=os.getenv("IMMICH_DLNA_LOG_LEVEL", "INFO"),
            ssdp_multicast_host=os.getenv("IMMICH_DLNA_SSDP_MULTICAST_HOST", "239.255.255.250"),
            ssdp_port=_read_int("IMMICH_DLNA_SSDP_PORT", 1900),
            ssdp_max_age=ssdp_max_age,
            ssdp_notify_interval=ssdp_notify_interval,
            immich_url=_normalize_immich_url(_read_required_str("IMMICH_URL")),
            immich_api_token=_read_required_str("IMMICH_API_TOKEN"),
            immich_verify_ssl=_read_bool("IMMICH_VERIFY_SSL", True),
            immich_timeout_seconds=immich_timeout_seconds,
            metadata_cache_ttl_seconds=metadata_cache_ttl_seconds,
            metadata_cache_max_entries=metadata_cache_max_entries,
            immich_max_concurrent_requests=immich_max_concurrent_requests,
        )
