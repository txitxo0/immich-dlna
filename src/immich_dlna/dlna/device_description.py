from __future__ import annotations

from xml.etree import ElementTree as ET

from immich_dlna.config import Settings

UPNP_DEVICE_NS = "urn:schemas-upnp-org:device-1-0"
DLNA_DEVICE_NS = "urn:schemas-dlna-org:device-1-0"

ET.register_namespace("dlna", DLNA_DEVICE_NS)


def _add_service(
    service_list: ET.Element,
    service_type: str,
    service_id: str,
    scpd_url: str,
    control_url: str,
    event_sub_url: str,
) -> None:
    service = ET.SubElement(service_list, "service")
    ET.SubElement(service, "serviceType").text = service_type
    ET.SubElement(service, "serviceId").text = service_id
    ET.SubElement(service, "SCPDURL").text = scpd_url
    ET.SubElement(service, "controlURL").text = control_url
    ET.SubElement(service, "eventSubURL").text = event_sub_url


def build_device_description(settings: Settings) -> str:
    root = ET.Element("root", {"xmlns": UPNP_DEVICE_NS})
    spec_version = ET.SubElement(root, "specVersion")
    ET.SubElement(spec_version, "major").text = "1"
    ET.SubElement(spec_version, "minor").text = "0"

    ET.SubElement(root, "URLBase").text = f"{settings.base_url}/"

    device = ET.SubElement(root, "device")
    ET.SubElement(device, "deviceType").text = "urn:schemas-upnp-org:device:MediaServer:1"
    ET.SubElement(device, "friendlyName").text = settings.friendly_name
    ET.SubElement(device, "manufacturer").text = "Immich-DLNA"
    ET.SubElement(device, "manufacturerURL").text = "https://github.com/immich-app/immich"
    ET.SubElement(device, "modelDescription").text = "Immich DLNA bridge"
    ET.SubElement(device, "modelName").text = "Immich-DLNA"
    ET.SubElement(device, "modelNumber").text = "phase1"
    ET.SubElement(device, "serialNumber").text = settings.server_uuid
    ET.SubElement(device, "UDN").text = f"uuid:{settings.server_uuid}"
    ET.SubElement(device, f"{{{DLNA_DEVICE_NS}}}X_DLNADOC").text = "DMS-1.50"
    ET.SubElement(device, "presentationURL").text = "/"

    service_list = ET.SubElement(device, "serviceList")
    _add_service(
        service_list,
        service_type="urn:schemas-upnp-org:service:ContentDirectory:1",
        service_id="urn:upnp-org:serviceId:ContentDirectory",
        scpd_url="/ContentDirectory/scpd.xml",
        control_url="/ContentDirectory/control",
        event_sub_url="/ContentDirectory/event",
    )
    _add_service(
        service_list,
        service_type="urn:schemas-upnp-org:service:ConnectionManager:1",
        service_id="urn:upnp-org:serviceId:ConnectionManager",
        scpd_url="/ConnectionManager/scpd.xml",
        control_url="/ConnectionManager/control",
        event_sub_url="/ConnectionManager/event",
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
