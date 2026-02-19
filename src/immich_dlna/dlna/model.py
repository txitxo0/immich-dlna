from __future__ import annotations

from dataclasses import dataclass

ROOT_ID = "0"
TIMELINE_ID = "timeline"
ALBUMS_ID = "albums"
CONTAINER_CLASS = "object.container.storageFolder"
IMAGE_CLASS = "object.item.imageItem.photo"
VIDEO_CLASS = "object.item.videoItem"


@dataclass(frozen=True, slots=True)
class Container:
    object_id: str
    parent_id: str
    title: str
    upnp_class: str = CONTAINER_CLASS
    child_count: int = 0
    searchable: bool = True
    storage_used: int = -1


@dataclass(frozen=True, slots=True)
class MediaItem:
    object_id: str
    parent_id: str
    title: str
    upnp_class: str
    resource_url: str
    thumbnail_url: str | None
    mime_type: str
    is_video: bool


BrowseEntry = Container | MediaItem


ROOT_CONTAINER = Container(object_id=ROOT_ID, parent_id="-1", title="Immich", child_count=2)
TIMELINE_CONTAINER = Container(object_id=TIMELINE_ID, parent_id=ROOT_ID, title="Timeline")
ALBUMS_CONTAINER = Container(object_id=ALBUMS_ID, parent_id=ROOT_ID, title="Albums")


def album_object_id(album_id: str) -> str:
    return f"album:{album_id}"


def asset_object_id(asset_id: str) -> str:
    return f"asset:{asset_id}"


def parse_album_id(object_id: str) -> str | None:
    if not object_id.startswith("album:"):
        return None
    album_id = object_id.split(":", 1)[1]
    return album_id or None


def parse_asset_id(object_id: str) -> str | None:
    if not object_id.startswith("asset:"):
        return None
    asset_id = object_id.split(":", 1)[1]
    return asset_id or None
