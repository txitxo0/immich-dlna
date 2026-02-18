from __future__ import annotations

from dataclasses import dataclass
import os
import socket
import uuid


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"Environment variable {name} must be an integer, got: {value}") from error


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

    @classmethod
    def from_env(cls) -> "Settings":
        http_port = _read_int("IMMICH_DLNA_HTTP_PORT", 8200)
        ssdp_max_age = _read_int("IMMICH_DLNA_SSDP_MAX_AGE", 1800)
        ssdp_notify_interval = _read_int("IMMICH_DLNA_SSDP_NOTIFY_INTERVAL", 900)

        if ssdp_notify_interval <= 0:
            raise ValueError("IMMICH_DLNA_SSDP_NOTIFY_INTERVAL must be > 0.")
        if ssdp_max_age <= 0:
            raise ValueError("IMMICH_DLNA_SSDP_MAX_AGE must be > 0.")
        if ssdp_notify_interval > ssdp_max_age:
            raise ValueError(
                "IMMICH_DLNA_SSDP_NOTIFY_INTERVAL must be <= IMMICH_DLNA_SSDP_MAX_AGE."
            )

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
        )
