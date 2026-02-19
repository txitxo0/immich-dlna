from __future__ import annotations

import logging
import time

import aiohttp
from aiohttp import web

from immich_dlna.config import Settings
from immich_dlna.dlna.connection_manager import ConnectionManagerService
from immich_dlna.dlna.content_directory import ContentDirectoryService
from immich_dlna.dlna.device_description import build_device_description
from immich_dlna.dlna.scpd import CONNECTION_MANAGER_SCPD, CONTENT_DIRECTORY_SCPD
from immich_dlna.dlna.soap import extract_action_from_soap_header, parse_action_request
from immich_dlna.immich import ImmichClient, ImmichError
from immich_dlna.metrics import MetricsRegistry


def _soap_response(status_code: int, payload: str) -> web.Response:
    return web.Response(status=status_code, text=payload, content_type="text/xml", charset="utf-8")


def create_app(
    settings: Settings,
    content_directory_service: ContentDirectoryService,
    connection_manager_service: ConnectionManagerService,
    immich_client: ImmichClient,
    metrics: MetricsRegistry,
) -> web.Application:
    @web.middleware
    async def request_metrics_middleware(
        request: web.Request,
        handler: web.Handler,
    ) -> web.StreamResponse:
        started_at = time.perf_counter()
        status = 500
        try:
            response = await handler(request)
            status = response.status
            return response
        except web.HTTPException as error:
            status = error.status
            raise
        finally:
            route = request.path
            route_info = request.match_info.route
            if route_info is not None:
                resource = getattr(route_info, "resource", None)
                canonical = getattr(resource, "canonical", None)
                if canonical:
                    route = canonical
            metrics.observe_request(
                method=request.method,
                route=route,
                status=status,
                duration_seconds=time.perf_counter() - started_at,
            )
            if status >= 500:
                metrics.increment_error("server")

    app = web.Application(middlewares=[request_metrics_middleware])
    logger = logging.getLogger("immich_dlna.http")

    async def _stream_upstream_response(
        request: web.Request,
        upstream: aiohttp.ClientResponse,
        default_content_type: str | None = None,
    ) -> web.StreamResponse:
        passthrough_headers = {}
        for header_name in (
            "Content-Type",
            "Content-Length",
            "Content-Range",
            "Accept-Ranges",
            "ETag",
            "Last-Modified",
            "Cache-Control",
        ):
            value = upstream.headers.get(header_name)
            if value:
                passthrough_headers[header_name] = value

        if default_content_type and "Content-Type" not in passthrough_headers:
            passthrough_headers["Content-Type"] = default_content_type

        response = web.StreamResponse(status=upstream.status, headers=passthrough_headers)
        await response.prepare(request)

        try:
            async for chunk in upstream.content.iter_chunked(64 * 1024):
                await response.write(chunk)
        except (ConnectionResetError, RuntimeError) as error:
            logger.warning("Client disconnected during upstream stream: %s", error)
        finally:
            upstream.release()

        try:
            await response.write_eof()
        except (ConnectionResetError, RuntimeError):
            pass
        return response

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "phase": 3})

    async def metrics_endpoint(_request: web.Request) -> web.Response:
        payload = metrics.render_prometheus(cache_hit_ratio=immich_client.cache_hit_ratio())
        return web.Response(
            body=payload,
            headers={"Content-Type": metrics.content_type},
        )

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
        status_code, payload = await content_directory_service.handle(action, body)
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

    async def media_asset(request: web.Request) -> web.StreamResponse:
        asset_id = request.match_info.get("asset_id", "")
        range_header = request.headers.get("Range")
        logger.info("Media proxy request asset_id=%s remote=%s has_range=%s", asset_id, request.remote, bool(range_header))

        try:
            asset, upstream = await immich_client.open_asset_stream(asset_id, range_header)
        except ImmichError as error:
            logger.error("Media proxy failed before stream asset_id=%s error=%s", asset_id, error)
            return web.Response(status=502, text="Failed to fetch media from Immich.")

        return await _stream_upstream_response(
            request=request,
            upstream=upstream,
            default_content_type=asset.original_mime_type,
        )

    async def media_asset_thumbnail(request: web.Request) -> web.StreamResponse:
        asset_id = request.match_info.get("asset_id", "")
        logger.info("Thumbnail proxy request asset_id=%s remote=%s", asset_id, request.remote)
        try:
            upstream = await immich_client.open_asset_thumbnail_stream(asset_id)
        except ImmichError as error:
            logger.error("Thumbnail proxy failed asset_id=%s error=%s", asset_id, error)
            return web.Response(status=502, text="Failed to fetch thumbnail from Immich.")

        content_type = (upstream.headers.get("Content-Type") or "").lower()
        logger.info(
            "Thumbnail upstream response asset_id=%s status=%s content_type=%s",
            asset_id,
            upstream.status,
            content_type or "<missing>",
        )
        if not content_type.startswith("image/") or content_type.startswith("image/webp"):
            upstream.release()
            try:
                asset, fallback_stream = await immich_client.open_asset_stream(asset_id, None)
            except ImmichError as error:
                logger.error("Thumbnail fallback failed asset_id=%s error=%s", asset_id, error)
                return web.Response(status=502, text="Failed to fetch thumbnail fallback.")
            if asset.is_video:
                fallback_stream.release()
                return web.Response(status=204)
            logger.info(
                "Thumbnail fallback to original asset stream asset_id=%s content_type=%s",
                asset_id,
                fallback_stream.headers.get("Content-Type", "<missing>"),
            )
            return await _stream_upstream_response(
                request=request,
                upstream=fallback_stream,
                default_content_type=asset.original_mime_type,
            )

        return await _stream_upstream_response(
            request=request,
            upstream=upstream,
            default_content_type="image/jpeg",
        )

    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics_endpoint)
    app.router.add_get("/device.xml", device_xml)
    app.router.add_get("/ContentDirectory/scpd.xml", content_directory_scpd)
    app.router.add_post("/ContentDirectory/control", content_directory_control)
    app.router.add_route("*", "/ContentDirectory/event", event_subscription)
    app.router.add_get("/ConnectionManager/scpd.xml", connection_manager_scpd)
    app.router.add_post("/ConnectionManager/control", connection_manager_control)
    app.router.add_route("*", "/ConnectionManager/event", event_subscription)
    app.router.add_get("/media/asset/{asset_id}", media_asset)
    app.router.add_get("/media/asset/{asset_id}/thumbnail", media_asset_thumbnail)
    return app
