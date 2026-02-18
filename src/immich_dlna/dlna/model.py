from __future__ import annotations

from dataclasses import dataclass

ROOT_ID = "0"
TIMELINE_ID = "timeline"
ALBUMS_ID = "albums"
CONTAINER_CLASS = "object.container.storageFolder"
TIMELINE_ALIASES = {TIMELINE_ID, "1"}
ALBUMS_ALIASES = {ALBUMS_ID, "2"}


@dataclass(frozen=True, slots=True)
class Container:
    object_id: str
    parent_id: str
    title: str
    upnp_class: str = CONTAINER_CLASS
    child_count: int = 0
    searchable: bool = True
    storage_used: int = -1


ROOT_CONTAINER = Container(object_id=ROOT_ID, parent_id="-1", title="Immich", child_count=2)
TIMELINE_CONTAINER = Container(object_id=TIMELINE_ID, parent_id=ROOT_ID, title="Timeline")
ALBUMS_CONTAINER = Container(object_id=ALBUMS_ID, parent_id=ROOT_ID, title="Albums")


def get_container(object_id: str) -> Container | None:
    if object_id == ROOT_ID:
        return ROOT_CONTAINER
    if object_id in TIMELINE_ALIASES:
        return TIMELINE_CONTAINER
    if object_id in ALBUMS_ALIASES:
        return ALBUMS_CONTAINER
    return None


def get_children(object_id: str) -> list[Container]:
    if object_id == ROOT_ID:
        return [TIMELINE_CONTAINER, ALBUMS_CONTAINER]
    if object_id in TIMELINE_ALIASES | ALBUMS_ALIASES:
        return []
    return []
