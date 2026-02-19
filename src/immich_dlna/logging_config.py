from __future__ import annotations

import logging


def _contains_connection_reset(exc: BaseException | None) -> bool:
    visited: set[int] = set()
    current = exc
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, ConnectionResetError):
            return True
        current = current.__cause__ or current.__context__
    return False


class _SuppressAiohttpClientResetFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "aiohttp.server":
            return True
        if "Error handling request from" not in record.getMessage():
            return True
        if not record.exc_info:
            return True
        exc = record.exc_info[1]
        return not _contains_connection_reset(exc)


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.server").addFilter(_SuppressAiohttpClientResetFilter())
