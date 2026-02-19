from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from aiohttp import web

from immich_dlna.config import Settings
from immich_dlna.dlna.catalog import ContentCatalog
from immich_dlna.dlna.connection_manager import ConnectionManagerService
from immich_dlna.dlna.content_directory import ContentDirectoryService
from immich_dlna.immich import ImmichClient
from immich_dlna.logging_config import configure_logging
from immich_dlna.metrics import MetricsRegistry
from immich_dlna.ssdp import SsdpServer
from immich_dlna.web import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Immich-DLNA server")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate environment configuration and exit.",
    )
    return parser.parse_args()


async def run_server(settings: Settings) -> None:
    logger = logging.getLogger("immich_dlna.main")
    metrics = MetricsRegistry(connected_device_ttl_seconds=settings.ssdp_max_age)
    immich_client = ImmichClient(settings, metrics=metrics)
    catalog = ContentCatalog(settings=settings, immich_client=immich_client)
    content_directory = ContentDirectoryService(catalog=catalog)
    connection_manager = ConnectionManagerService()
    ssdp_server = SsdpServer(settings, metrics=metrics)
    app = create_app(settings, content_directory, connection_manager, immich_client, metrics)

    async def on_startup(_app: web.Application) -> None:
        await immich_client.start()
        logger.info("Immich client started")
        await ssdp_server.start()
        logger.info("SSDP started")

    async def on_cleanup(_app: web.Application) -> None:
        await ssdp_server.stop()
        logger.info("SSDP stopped")
        await immich_client.close()
        logger.info("Immich client stopped")

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.http_host, port=settings.http_port)
    await site.start()

    logger.info(
        "HTTP server started host=%s port=%s base_url=%s friendly_name=%s",
        settings.http_host,
        settings.http_port,
        settings.base_url,
        settings.friendly_name,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop_event.set)
        except NotImplementedError:
            pass

    await stop_event.wait()
    logger.info("Shutdown requested")
    await runner.cleanup()


def main() -> None:
    args = parse_args()
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    logger = logging.getLogger("immich_dlna.main")
    if args.check_config:
        logger.info(
            "Configuration valid. base_url=%s server_uuid=%s",
            settings.base_url,
            settings.server_uuid,
        )
        return

    try:
        asyncio.run(run_server(settings))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
