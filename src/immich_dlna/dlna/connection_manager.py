from __future__ import annotations

import logging

from immich_dlna.dlna.soap import render_soap_fault, render_soap_response

SERVICE_NAMESPACE = "urn:schemas-upnp-org:service:ConnectionManager:1"


class ConnectionManagerService:
    def __init__(self) -> None:
        self.logger = logging.getLogger("immich_dlna.connection_manager")

    def handle(self, action_name: str) -> tuple[int, str]:
        if action_name == "GetProtocolInfo":
            payload = render_soap_response(
                SERVICE_NAMESPACE,
                action_name,
                {
                    "Source": "http-get:*:image/jpeg:*,http-get:*:video/mp4:*",
                    "Sink": "",
                },
            )
            return 200, payload

        if action_name == "GetCurrentConnectionIDs":
            payload = render_soap_response(SERVICE_NAMESPACE, action_name, {"ConnectionIDs": "0"})
            return 200, payload

        if action_name == "GetCurrentConnectionInfo":
            payload = render_soap_response(
                SERVICE_NAMESPACE,
                action_name,
                {
                    "RcsID": "-1",
                    "AVTransportID": "-1",
                    "ProtocolInfo": "",
                    "PeerConnectionManager": "",
                    "PeerConnectionID": "-1",
                    "Direction": "Output",
                    "Status": "OK",
                },
            )
            return 200, payload

        self.logger.warning("Unsupported ConnectionManager action requested: %s", action_name)
        return 500, render_soap_fault(401, "Invalid Action")
