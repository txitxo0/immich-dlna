from __future__ import annotations

from xml.etree import ElementTree as ET

from immich_dlna.dlna.model import Container

DIDL_NS = "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
DC_NS = "http://purl.org/dc/elements/1.1/"
UPNP_NS = "urn:schemas-upnp-org:metadata-1-0/upnp/"
DLNA_NS = "urn:schemas-dlna-org:metadata-1-0/"

ET.register_namespace("", DIDL_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("upnp", UPNP_NS)
ET.register_namespace("dlna", DLNA_NS)


def render_containers(containers: list[Container]) -> str:
    root = ET.Element(f"{{{DIDL_NS}}}DIDL-Lite")
    for container in containers:
        container_element = ET.SubElement(
            root,
            f"{{{DIDL_NS}}}container",
            {
                "id": container.object_id,
                "parentID": container.parent_id,
                "restricted": "1",
                "searchable": "1" if container.searchable else "0",
                "childCount": str(container.child_count),
            },
        )
        title = ET.SubElement(container_element, f"{{{DC_NS}}}title")
        title.text = container.title
        upnp_class = ET.SubElement(container_element, f"{{{UPNP_NS}}}class")
        upnp_class.text = container.upnp_class
        storage_used = ET.SubElement(container_element, f"{{{UPNP_NS}}}storageUsed")
        storage_used.text = str(container.storage_used)
    return ET.tostring(root, encoding="unicode")
