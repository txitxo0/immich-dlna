from __future__ import annotations

from xml.etree import ElementTree as ET

from immich_dlna.dlna.model import BrowseEntry, Container, MediaItem

DIDL_NS = "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
DC_NS = "http://purl.org/dc/elements/1.1/"
UPNP_NS = "urn:schemas-upnp-org:metadata-1-0/upnp/"
DLNA_NS = "urn:schemas-dlna-org:metadata-1-0/"

ET.register_namespace("", DIDL_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("upnp", UPNP_NS)
ET.register_namespace("dlna", DLNA_NS)


def _protocol_info(item: MediaItem) -> str:
    if item.is_video:
        return f"http-get:*:{item.mime_type}:DLNA.ORG_OP=01;DLNA.ORG_CI=0"
    return f"http-get:*:{item.mime_type}:*"


def render_entries(entries: list[BrowseEntry]) -> str:
    root = ET.Element(f"{{{DIDL_NS}}}DIDL-Lite")
    for entry in entries:
        if isinstance(entry, Container):
            container_element = ET.SubElement(
                root,
                f"{{{DIDL_NS}}}container",
                {
                    "id": entry.object_id,
                    "parentID": entry.parent_id,
                    "restricted": "1",
                    "searchable": "1" if entry.searchable else "0",
                    "childCount": str(entry.child_count),
                },
            )
            title = ET.SubElement(container_element, f"{{{DC_NS}}}title")
            title.text = entry.title
            upnp_class = ET.SubElement(container_element, f"{{{UPNP_NS}}}class")
            upnp_class.text = entry.upnp_class
            storage_used = ET.SubElement(container_element, f"{{{UPNP_NS}}}storageUsed")
            storage_used.text = str(entry.storage_used)
            continue

        item = ET.SubElement(
            root,
            f"{{{DIDL_NS}}}item",
            {
                "id": entry.object_id,
                "parentID": entry.parent_id,
                "restricted": "1",
            },
        )
        title = ET.SubElement(item, f"{{{DC_NS}}}title")
        title.text = entry.title
        upnp_class = ET.SubElement(item, f"{{{UPNP_NS}}}class")
        upnp_class.text = entry.upnp_class
        if entry.thumbnail_url:
            album_art = ET.SubElement(item, f"{{{UPNP_NS}}}albumArtURI")
            album_art.text = entry.thumbnail_url
        resource = ET.SubElement(item, f"{{{DIDL_NS}}}res", {"protocolInfo": _protocol_info(entry)})
        resource.text = entry.resource_url
    return ET.tostring(root, encoding="unicode")
