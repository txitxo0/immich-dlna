from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import socket
from urllib.parse import urlsplit

from immich_dlna.config import Settings
from immich_dlna.metrics import MetricsRegistry

MEDIA_SERVER_DEVICE_TYPE = "urn:schemas-upnp-org:device:MediaServer:1"
CONTENT_DIRECTORY_SERVICE_TYPE = "urn:schemas-upnp-org:service:ContentDirectory:1"
CONNECTION_MANAGER_SERVICE_TYPE = "urn:schemas-upnp-org:service:ConnectionManager:1"


@dataclass(frozen=True, slots=True)
class Announcement:
    target: str
    usn: str


class _SsdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: "SsdpServer") -> None:
        self.server = server

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.server.handle_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:
        self.server.logger.warning("SSDP socket error: %s", exc)


class SsdpServer:
    def __init__(self, settings: Settings, metrics: MetricsRegistry) -> None:
        self.settings = settings
        self.metrics = metrics
        self.logger = logging.getLogger("immich_dlna.ssdp")
        self._transport: asyncio.DatagramTransport | None = None
        self._notify_task: asyncio.Task[None] | None = None

    @property
    def _server_header(self) -> str:
        return "Linux/6.0 UPnP/1.0 Immich-DLNA/0.1"

    @property
    def _default_location(self) -> str:
        return f"{self.settings.base_url}/device.xml"

    @property
    def _announcements(self) -> list[Announcement]:
        uuid_value = f"uuid:{self.settings.server_uuid}"
        return [
            Announcement("upnp:rootdevice", f"{uuid_value}::upnp:rootdevice"),
            Announcement(uuid_value, uuid_value),
            Announcement(MEDIA_SERVER_DEVICE_TYPE, f"{uuid_value}::{MEDIA_SERVER_DEVICE_TYPE}"),
            Announcement(
                CONTENT_DIRECTORY_SERVICE_TYPE,
                f"{uuid_value}::{CONTENT_DIRECTORY_SERVICE_TYPE}",
            ),
            Announcement(
                CONNECTION_MANAGER_SERVICE_TYPE,
                f"{uuid_value}::{CONNECTION_MANAGER_SERVICE_TYPE}",
            ),
        ]

    async def start(self) -> None:
        self.logger.info(
            "Starting SSDP listener on %s:%s",
            self.settings.ssdp_multicast_host,
            self.settings.ssdp_port,
        )
        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen_socket.bind(("", self.settings.ssdp_port))
        membership = socket.inet_aton(self.settings.ssdp_multicast_host) + socket.inet_aton("0.0.0.0")
        listen_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        listen_socket.setblocking(False)

        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _SsdpProtocol(self),
            sock=listen_socket,
        )
        self._transport = transport
        await self._send_notify("ssdp:alive")
        self._notify_task = asyncio.create_task(self._notify_loop())

    async def stop(self) -> None:
        if self._notify_task is not None:
            self._notify_task.cancel()
            try:
                await self._notify_task
            except asyncio.CancelledError:
                pass
            self._notify_task = None
        await self._send_notify("ssdp:byebye")
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    async def _notify_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.ssdp_notify_interval)
            await self._send_notify("ssdp:alive")

    async def _send_notify(self, nts_value: str) -> None:
        for announcement in self._announcements:
            message = self._build_notify_message(announcement, nts_value)
            self._send_datagram(
                message,
                (self.settings.ssdp_multicast_host, self.settings.ssdp_port),
            )
            self.logger.debug("SSDP NOTIFY sent nts=%s nt=%s", nts_value, announcement.target)

    def handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        message = data.decode("utf-8", errors="replace")
        if not message.startswith("M-SEARCH * HTTP/1.1"):
            return
        headers = self._parse_headers(message)
        man_value = headers.get("man", "").strip().strip('"').lower()
        if man_value != "ssdp:discover":
            return
        search_target = headers.get("st", "")
        if not search_target:
            return

        self.logger.info("M-SEARCH received from %s st=%s", addr[0], search_target)
        self.metrics.mark_device_seen(addr[0])
        location = self._location_for_destination(addr[0])

        if search_target == "ssdp:all":
            for announcement in self._announcements:
                response = self._build_search_response(
                    st_value=announcement.target,
                    usn_value=announcement.usn,
                    location=location,
                )
                self._send_datagram(response, addr)
                self.logger.info(
                    "M-SEARCH response sent to %s:%s st=%s location=%s",
                    addr[0],
                    addr[1],
                    announcement.target,
                    location,
                )
            return

        matched = [item for item in self._announcements if item.target == search_target]

        for announcement in matched:
            response = self._build_search_response(
                st_value=announcement.target,
                usn_value=announcement.usn,
                location=location,
            )
            self._send_datagram(response, addr)
            self.logger.info(
                "M-SEARCH response sent to %s:%s st=%s location=%s",
                addr[0],
                addr[1],
                announcement.target,
                location,
            )

    def _send_datagram(self, payload: str, destination: tuple[str, int]) -> None:
        if self._transport is None:
            return
        self._transport.sendto(payload.encode("utf-8"), destination)

    def _build_search_response(self, st_value: str, usn_value: str, location: str) -> str:
        lines = [
            "HTTP/1.1 200 OK",
            f"CACHE-CONTROL: max-age={self.settings.ssdp_max_age}",
            f"DATE: {self._http_date()}",
            "EXT:",
            f"LOCATION: {location}",
            f"SERVER: {self._server_header}",
            "BOOTID.UPNP.ORG: 1",
            "CONFIGID.UPNP.ORG: 1",
            f"ST: {st_value}",
            f"USN: {usn_value}",
            "CONTENT-LENGTH: 0",
            "",
            "",
        ]
        return "\r\n".join(lines)

    def _build_notify_message(self, announcement: Announcement, nts_value: str) -> str:
        lines = [
            "NOTIFY * HTTP/1.1",
            f"HOST: {self.settings.ssdp_multicast_host}:{self.settings.ssdp_port}",
            f"NT: {announcement.target}",
            f"NTS: {nts_value}",
            f"USN: {announcement.usn}",
            f"SERVER: {self._server_header}",
            "BOOTID.UPNP.ORG: 1",
            "CONFIGID.UPNP.ORG: 1",
        ]
        if nts_value == "ssdp:alive":
            lines.extend(
                [
                    f"LOCATION: {self._default_location}",
                    f"CACHE-CONTROL: max-age={self.settings.ssdp_max_age}",
                ]
            )
        lines.extend(["", ""])
        return "\r\n".join(lines)

    def _location_for_destination(self, destination_ip: str) -> str:
        parsed_base_url = urlsplit(self.settings.base_url)
        scheme = parsed_base_url.scheme or "http"
        port = parsed_base_url.port or self.settings.http_port
        default_host = parsed_base_url.hostname or "127.0.0.1"

        resolved_host = default_host
        probe_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe_socket.connect((destination_ip, 9))
            candidate = probe_socket.getsockname()[0]
            if candidate and not candidate.startswith("127."):
                resolved_host = candidate
        except OSError:
            pass
        finally:
            probe_socket.close()

        return f"{scheme}://{resolved_host}:{port}/device.xml"

    @staticmethod
    def _parse_headers(message: str) -> dict[str, str]:
        lines = message.split("\r\n")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        return headers

    @staticmethod
    def _http_date() -> str:
        now = datetime.now(tz=timezone.utc)
        return now.strftime("%a, %d %b %Y %H:%M:%S GMT")
