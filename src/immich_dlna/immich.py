from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re
import time
from typing import Any

import aiohttp

from immich_dlna.cache import TtlCache
from immich_dlna.config import Settings
from immich_dlna.metrics import MetricsRegistry


class ImmichError(RuntimeError):
    pass


_UUID_IN_PATH = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)"
)


@dataclass(frozen=True, slots=True)
class ImmichAlbum:
    album_id: str
    name: str
    created_at: str
    asset_count: int


@dataclass(frozen=True, slots=True)
class ImmichAsset:
    asset_id: str
    title: str
    original_mime_type: str
    is_video: bool
    created_at: str


class ImmichClient:
    def __init__(self, settings: Settings, metrics: MetricsRegistry | None = None) -> None:
        self.settings = settings
        self.metrics = metrics
        self.logger = logging.getLogger("immich_dlna.immich")
        self._session: aiohttp.ClientSession | None = None
        self._asset_cache = TtlCache[ImmichAsset](
            settings.metadata_cache_ttl_seconds,
            settings.metadata_cache_max_entries,
        )
        self._album_list_cache = TtlCache[list[ImmichAlbum]](
            settings.metadata_cache_ttl_seconds,
            settings.metadata_cache_max_entries,
        )
        self._album_assets_cache = TtlCache[list[ImmichAsset]](
            settings.metadata_cache_ttl_seconds,
            settings.metadata_cache_max_entries,
        )
        self._timeline_refs_cache = TtlCache[list[tuple[str, bool]]](
            settings.metadata_cache_ttl_seconds,
            settings.metadata_cache_max_entries,
        )
        self._ssl: bool | None = None if settings.immich_verify_ssl else False

    async def start(self) -> None:
        if self._session is not None:
            return
        timeout = aiohttp.ClientTimeout(total=self.settings.immich_timeout_seconds)
        connector = aiohttp.TCPConnector(
            limit=self.settings.immich_max_concurrent_requests,
            limit_per_host=self.settings.immich_max_concurrent_requests,
        )
        self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        self.logger.info(
            "Immich client started url=%s verify_ssl=%s max_concurrent_requests=%s",
            self.settings.immich_url,
            self.settings.immich_verify_ssl,
            self.settings.immich_max_concurrent_requests,
        )

    async def close(self) -> None:
        if self._session is None:
            return
        await self._session.close()
        self._session = None

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.settings.immich_api_token,
            "Accept": "application/json",
        }

    @staticmethod
    def _metric_target(path: str) -> str:
        normalized = _UUID_IN_PATH.sub("/{id}", path)
        return normalized or "/"

    def _observe_outgoing(self, path: str, status: str, duration_seconds: float) -> None:
        if self.metrics is None:
            return
        self.metrics.observe_outgoing(
            method="GET",
            target=self._metric_target(path),
            status=status,
            duration_seconds=duration_seconds,
        )

    def _record_immich_error(self) -> None:
        if self.metrics is None:
            return
        self.metrics.increment_error("immich")

    def cache_hit_ratio(self) -> float:
        caches = (
            self._asset_cache,
            self._album_list_cache,
            self._album_assets_cache,
            self._timeline_refs_cache,
        )
        hits = sum(cache.hits for cache in caches)
        misses = sum(cache.misses for cache in caches)
        total = hits + misses
        if total == 0:
            return 0.0
        return hits / total

    async def _request_json(
        self,
        path: str,
        params: dict[str, str] | None = None,
        retries: int = 1,
    ) -> Any:
        session = self._session
        if session is None:
            raise RuntimeError("Immich client not started.")
        url = f"{self.settings.immich_url}{path}"
        attempt = 0
        while True:
            started_at = time.perf_counter()
            try:
                async with session.get(url, headers=self._headers(), params=params, ssl=self._ssl) as response:
                    if response.status >= 400:
                        details = (await response.text())[:250]
                        self._observe_outgoing(path, str(response.status), time.perf_counter() - started_at)
                        self._record_immich_error()
                        raise ImmichError(f"Immich GET {path} failed: {response.status} {details}")
                    content_type = response.headers.get("Content-Type", "")
                    if "json" not in content_type.lower():
                        details = (await response.text())[:250]
                        self._observe_outgoing(path, str(response.status), time.perf_counter() - started_at)
                        self._record_immich_error()
                        raise ImmichError(
                            f"Immich GET {path} returned non-JSON content type ({content_type}). "
                            f"Check IMMICH_URL points to Immich API (usually with /api). Response: {details}"
                        )
                    payload = await response.json()
                    self._observe_outgoing(path, str(response.status), time.perf_counter() - started_at)
                    return payload
            except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                self._observe_outgoing(path, "error", time.perf_counter() - started_at)
                self._record_immich_error()
                if attempt >= retries:
                    raise ImmichError(str(error)) from error
                attempt += 1
                await asyncio.sleep(0.2 * attempt)
            except ImmichError as error:
                if attempt >= retries:
                    raise ImmichError(str(error)) from error
                attempt += 1
                await asyncio.sleep(0.2 * attempt)

    async def list_albums(self) -> list[ImmichAlbum]:
        cached = self._album_list_cache.get("albums")
        if cached is not None:
            return cached

        owned_payload = await self._request_json("/albums")
        shared_payload = await self._request_json("/albums", params={"shared": "true"})

        albums_by_id: dict[str, ImmichAlbum] = {}
        for payload in (owned_payload, shared_payload):
            for album in payload:
                parsed_album = ImmichAlbum(
                    album_id=str(album.get("id", "")),
                    name=str(album.get("albumName", "Album")),
                    created_at=str(album.get("createdAt", "")),
                    asset_count=int(album.get("assetCount", 0)),
                )
                if parsed_album.album_id:
                    albums_by_id[parsed_album.album_id] = parsed_album

        albums = list(albums_by_id.values())
        self._album_list_cache.set("albums", albums)
        return albums

    async def get_album_assets(self, album_id: str, sort_criteria: str = "") -> list[ImmichAsset]:
        cache_key = f"album:{album_id}"
        cached = self._album_assets_cache.get(cache_key)
        if cached is not None and not sort_criteria:
            return cached

        payload = await self._request_json(f"/albums/{album_id}", params={"withoutAssets": "false"})
        assets_payload = payload.get("assets", [])
        assets = [self._parse_asset(asset_payload) for asset_payload in assets_payload]
        album_order = str(payload.get("order", "")).strip().lower()
        if not sort_criteria and album_order in {"asc", "desc"}:
            assets.sort(key=lambda asset: asset.created_at, reverse=album_order == "desc")
        for asset in assets:
            self._asset_cache.set(f"asset:{asset.asset_id}", asset)
        if not sort_criteria:
            self._album_assets_cache.set(cache_key, assets)
        return assets

    async def list_timeline_asset_refs(self) -> list[tuple[str, bool]]:
        cached = self._timeline_refs_cache.get("timeline")
        if cached is not None:
            return cached

        bucket_payload = await self._request_json(
            "/timeline/buckets",
            params={
                "order": "desc",
                "visibility": "timeline",
                "isTrashed": "false",
                "withPartners": "true",
            },
        )

        refs: list[tuple[str, bool]] = []
        for bucket in bucket_payload:
            time_bucket = str(bucket.get("timeBucket", ""))
            if not time_bucket:
                continue
            assets_payload = await self._request_json(
                "/timeline/bucket",
                params={
                    "timeBucket": time_bucket,
                    "order": "desc",
                    "visibility": "timeline",
                    "isTrashed": "false",
                    "withPartners": "true",
                },
            )
            ids = assets_payload.get("id", [])
            image_flags = assets_payload.get("isImage", [])
            for index, asset_id in enumerate(ids):
                is_image = True
                if index < len(image_flags):
                    is_image = bool(image_flags[index])
                refs.append((str(asset_id), is_image))

        self._timeline_refs_cache.set("timeline", refs)
        return refs

    async def get_asset_info(self, asset_id: str, fallback_is_image: bool | None = None) -> ImmichAsset:
        cache_key = f"asset:{asset_id}"
        cached = self._asset_cache.get(cache_key)
        if cached is not None:
            return cached

        payload = await self._request_json(f"/assets/{asset_id}")
        asset = self._parse_asset(payload, fallback_is_image=fallback_is_image)
        self._asset_cache.set(cache_key, asset)
        return asset

    async def open_asset_stream(
        self,
        asset_id: str,
        range_header: str | None,
    ) -> tuple[ImmichAsset, aiohttp.ClientResponse]:
        session = self._session
        if session is None:
            raise RuntimeError("Immich client not started.")

        asset = await self.get_asset_info(asset_id)
        if asset.is_video:
            path = f"/assets/{asset_id}/video/playback"
        else:
            path = f"/assets/{asset_id}/original"

        headers = {"x-api-key": self.settings.immich_api_token}
        if range_header:
            headers["Range"] = range_header

        url = f"{self.settings.immich_url}{path}"
        started_at = time.perf_counter()
        try:
            response = await session.get(url, headers=headers, ssl=self._ssl)
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            self._observe_outgoing(path, "error", time.perf_counter() - started_at)
            self._record_immich_error()
            raise ImmichError(f"Immich stream request failed: {error}") from error
        self._observe_outgoing(path, str(response.status), time.perf_counter() - started_at)
        if response.status >= 400:
            details = (await response.text())[:250]
            response.release()
            self._record_immich_error()
            raise ImmichError(f"Immich stream {path} failed: {response.status} {details}")
        return asset, response

    async def open_asset_thumbnail_stream(self, asset_id: str) -> aiohttp.ClientResponse:
        session = self._session
        if session is None:
            raise RuntimeError("Immich client not started.")

        headers = {
            "x-api-key": self.settings.immich_api_token,
            "Accept": "image/jpeg,image/*;q=0.9,*/*;q=0.1",
        }
        url = f"{self.settings.immich_url}/assets/{asset_id}/thumbnail"
        started_at = time.perf_counter()
        try:
            response = await session.get(url, headers=headers, params={"size": "preview"}, ssl=self._ssl)
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            self._observe_outgoing("/assets/{id}/thumbnail", "error", time.perf_counter() - started_at)
            self._record_immich_error()
            raise ImmichError(f"Immich thumbnail request failed: {error}") from error
        self._observe_outgoing("/assets/{id}/thumbnail", str(response.status), time.perf_counter() - started_at)
        if response.status >= 400:
            details = (await response.text())[:250]
            response.release()
            self._record_immich_error()
            raise ImmichError(f"Immich thumbnail failed: {response.status} {details}")
        return response

    @staticmethod
    def _parse_asset(payload: dict[str, Any], fallback_is_image: bool | None = None) -> ImmichAsset:
        asset_id = str(payload.get("id", ""))
        asset_type = str(payload.get("type", "IMAGE")).upper()
        if asset_type in {"VIDEO", "AUDIO"}:
            is_video = True
        elif asset_type in {"IMAGE", "OTHER"}:
            is_video = False
        elif fallback_is_image is not None:
            is_video = not fallback_is_image
        else:
            is_video = False

        mime_type = str(payload.get("originalMimeType", "")).strip()
        if not mime_type:
            mime_type = "video/mp4" if is_video else "image/jpeg"

        title = str(payload.get("originalFileName", "")).strip() or asset_id
        created_at = str(payload.get("fileCreatedAt") or payload.get("createdAt") or "")
        return ImmichAsset(
            asset_id=asset_id,
            title=title,
            original_mime_type=mime_type,
            is_video=is_video,
            created_at=created_at,
        )
