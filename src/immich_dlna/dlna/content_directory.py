from __future__ import annotations

import logging

from immich_dlna.dlna.didl import render_containers
from immich_dlna.dlna.model import get_children, get_container
from immich_dlna.dlna.soap import child_text, parse_action_request, render_soap_fault, render_soap_response

SERVICE_NAMESPACE = "urn:schemas-upnp-org:service:ContentDirectory:1"


def _parse_non_negative_int(value: str, default: int = 0) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(parsed, 0)


class ContentDirectoryService:
    def __init__(self) -> None:
        self.logger = logging.getLogger("immich_dlna.content_directory")

    def handle(self, action_name: str, body: bytes) -> tuple[int, str]:
        if action_name == "Browse":
            return self._handle_browse(body)
        if action_name == "GetSystemUpdateID":
            payload = render_soap_response(SERVICE_NAMESPACE, action_name, {"Id": "1"})
            return 200, payload
        if action_name == "GetSearchCapabilities":
            payload = render_soap_response(SERVICE_NAMESPACE, action_name, {"SearchCaps": ""})
            return 200, payload
        if action_name == "GetSortCapabilities":
            payload = render_soap_response(SERVICE_NAMESPACE, action_name, {"SortCaps": ""})
            return 200, payload

        self.logger.warning("Unsupported ContentDirectory action requested: %s", action_name)
        return 500, render_soap_fault(401, "Invalid Action")

    def _handle_browse(self, body: bytes) -> tuple[int, str]:
        try:
            _, action_element = parse_action_request(body)
        except ValueError as error:
            self.logger.warning("Failed to parse Browse request: %s", error)
            return 500, render_soap_fault(402, "Invalid Args")

        object_id = child_text(action_element, "ObjectID", "0")
        browse_flag = child_text(action_element, "BrowseFlag", "BrowseDirectChildren")
        starting_index = _parse_non_negative_int(child_text(action_element, "StartingIndex", "0"))
        requested_count = _parse_non_negative_int(child_text(action_element, "RequestedCount", "0"))
        if requested_count == 0:
            requested_count = 50

        if browse_flag == "BrowseMetadata":
            container = get_container(object_id)
            all_entries = [container] if container is not None else []
        elif browse_flag == "BrowseDirectChildren":
            all_entries = get_children(object_id)
        else:
            self.logger.warning("Unsupported BrowseFlag value: %s", browse_flag)
            return 500, render_soap_fault(402, "Invalid Args")

        total_matches = len(all_entries)
        paged_entries = all_entries[starting_index : starting_index + requested_count]
        didl_result = render_containers(paged_entries)

        self.logger.info(
            "Browse handled object_id=%s browse_flag=%s start=%s requested=%s returned=%s total=%s",
            object_id,
            browse_flag,
            starting_index,
            requested_count,
            len(paged_entries),
            total_matches,
        )

        payload = render_soap_response(
            SERVICE_NAMESPACE,
            "Browse",
            {
                "Result": didl_result,
                "NumberReturned": str(len(paged_entries)),
                "TotalMatches": str(total_matches),
                "UpdateID": "1",
            },
        )
        return 200, payload
