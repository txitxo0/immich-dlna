from __future__ import annotations

import logging

from aiohttp import web

from immich_dlna.config import Settings
from immich_dlna.dlna.connection_manager import ConnectionManagerService
from immich_dlna.dlna.content_directory import ContentDirectoryService
from immich_dlna.dlna.device_description import build_device_description
from immich_dlna.dlna.scpd import CONNECTION_MANAGER_SCPD, CONTENT_DIRECTORY_SCPD
from immich_dlna.dlna.soap import extract_action_from_soap_header, parse_action_request


def _soap_response(status_code: int, payload: str) -> web.Response:
    return web.Response(status=status_code, text=payload, content_type="text/xml", charset="utf-8")


def create_app(
    settings: Settings,
    content_directory_service: ContentDirectoryService,
    connection_manager_service: ConnectionManagerService,
) -> web.Application:
    app = web.Application()
    logger = logging.getLogger("immich_dlna.http")

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "phase": 1})

    async def device_xml(request: web.Request) -> web.Response:
        logger.info("Device description requested remote=%s", request.remote)
        xml_payload = build_device_description(settings)
        return web.Response(text=xml_payload, content_type="text/xml", charset="utf-8")

    async def content_directory_scpd(request: web.Request) -> web.Response:
        logger.info("ContentDirectory SCPD requested remote=%s", request.remote)
        return web.Response(text=CONTENT_DIRECTORY_SCPD, content_type="text/xml", charset="utf-8")

    async def connection_manager_scpd(request: web.Request) -> web.Response:
        logger.info("ConnectionManager SCPD requested remote=%s", request.remote)
        return web.Response(text=CONNECTION_MANAGER_SCPD, content_type="text/xml", charset="utf-8")

    async def event_subscription(request: web.Request) -> web.Response:
        service_name = "ContentDirectory" if request.path.startswith("/ContentDirectory/") else "ConnectionManager"
        logger.info(
            "%s event endpoint called method=%s remote=%s",
            service_name,
            request.method,
            request.remote,
        )
        headers: dict[str, str] = {}
        if request.method.upper() == "SUBSCRIBE":
            headers["SID"] = request.headers.get("SID", f"uuid:{settings.server_uuid}")
            headers["TIMEOUT"] = request.headers.get("TIMEOUT", "Second-1800")
        return web.Response(status=200, headers=headers)

    async def content_directory_control(request: web.Request) -> web.Response:
        body = await request.read()
        action = extract_action_from_soap_header(request.headers.get("SOAPAction"))
        if action is None:
            try:
                action, _ = parse_action_request(body)
            except ValueError:
                logger.warning("Rejected malformed ContentDirectory SOAP request from %s", request.remote)
                return web.Response(status=400, text="Malformed SOAP request.")

        logger.info("ContentDirectory action=%s remote=%s", action, request.remote)
        status_code, payload = content_directory_service.handle(action, body)
        return _soap_response(status_code, payload)

    async def connection_manager_control(request: web.Request) -> web.Response:
        body = await request.read()
        action = extract_action_from_soap_header(request.headers.get("SOAPAction"))
        if action is None:
            try:
                action, _ = parse_action_request(body)
            except ValueError:
                logger.warning("Rejected malformed ConnectionManager SOAP request from %s", request.remote)
                return web.Response(status=400, text="Malformed SOAP request.")

        logger.info("ConnectionManager action=%s remote=%s", action, request.remote)
        status_code, payload = connection_manager_service.handle(action)
        return _soap_response(status_code, payload)

    app.router.add_get("/health", health)
    app.router.add_get("/device.xml", device_xml)
    app.router.add_get("/ContentDirectory/scpd.xml", content_directory_scpd)
    app.router.add_post("/ContentDirectory/control", content_directory_control)
    app.router.add_route("*", "/ContentDirectory/event", event_subscription)
    app.router.add_get("/ConnectionManager/scpd.xml", connection_manager_scpd)
    app.router.add_post("/ConnectionManager/control", connection_manager_control)
    app.router.add_route("*", "/ConnectionManager/event", event_subscription)
    return app
