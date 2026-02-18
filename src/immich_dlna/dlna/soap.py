from __future__ import annotations

from xml.etree import ElementTree as ET

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
UPNP_CONTROL_NS = "urn:schemas-upnp-org:control-1-0"
SOAP_ENCODING_STYLE = "http://schemas.xmlsoap.org/soap/encoding/"

ET.register_namespace("s", SOAP_NS)


def local_name(tag: str) -> str:
    if "}" not in tag:
        return tag
    return tag.rsplit("}", 1)[1]


def parse_action_request(body: bytes) -> tuple[str, ET.Element]:
    try:
        envelope = ET.fromstring(body)
    except ET.ParseError as error:
        raise ValueError("Invalid SOAP XML payload.") from error
    soap_body = envelope.find(f".//{{{SOAP_NS}}}Body")
    if soap_body is None or not list(soap_body):
        raise ValueError("SOAP body is missing action payload.")
    action_element = list(soap_body)[0]
    return local_name(action_element.tag), action_element


def child_text(action_element: ET.Element, name: str, default: str = "") -> str:
    for child in action_element:
        if local_name(child.tag) == name:
            return (child.text or "").strip()
    return default


def extract_action_from_soap_header(header_value: str | None) -> str | None:
    if not header_value:
        return None
    normalized = header_value.strip().strip('"')
    if "#" not in normalized:
        return None
    return normalized.rsplit("#", 1)[1]


def render_soap_response(service_namespace: str, action_name: str, fields: dict[str, str]) -> str:
    ET.register_namespace("u", service_namespace)
    envelope = ET.Element(
        f"{{{SOAP_NS}}}Envelope",
        {f"{{{SOAP_NS}}}encodingStyle": SOAP_ENCODING_STYLE},
    )
    body = ET.SubElement(envelope, f"{{{SOAP_NS}}}Body")
    response = ET.SubElement(body, f"{{{service_namespace}}}{action_name}Response")
    for key, value in fields.items():
        field = ET.SubElement(response, key)
        field.text = value
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True).decode("utf-8")


def render_soap_fault(error_code: int, error_description: str) -> str:
    envelope = ET.Element(
        f"{{{SOAP_NS}}}Envelope",
        {f"{{{SOAP_NS}}}encodingStyle": SOAP_ENCODING_STYLE},
    )
    body = ET.SubElement(envelope, f"{{{SOAP_NS}}}Body")
    fault = ET.SubElement(body, f"{{{SOAP_NS}}}Fault")
    fault_code = ET.SubElement(fault, "faultcode")
    fault_code.text = "s:Client"
    fault_string = ET.SubElement(fault, "faultstring")
    fault_string.text = "UPnPError"
    detail = ET.SubElement(fault, "detail")
    upnp_error = ET.SubElement(detail, f"{{{UPNP_CONTROL_NS}}}UPnPError")
    code = ET.SubElement(upnp_error, "errorCode")
    code.text = str(error_code)
    description = ET.SubElement(upnp_error, "errorDescription")
    description.text = error_description
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True).decode("utf-8")
