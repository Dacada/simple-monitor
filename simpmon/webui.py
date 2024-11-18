#!/usr/bin/env python3

import http.server
import json
import logging
import threading
from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from simpmon import config, monitor

logger = logging.getLogger(__name__)


class MonitorHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    def __init__(
        self, monitor_collection: monitor.MonitorCollection, *args: Any, **kwargs: Any
    ) -> None:
        self.monitor_collection = monitor_collection
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        parsed_path = urlparse(self.path)

        files = {
            "/": ("index.html", "text/html"),
            "/index.html": ("index.html", "text/html"),
            "/script.js": ("script.js", "application/javascript"),
            "/styles.css": ("styles.css", "text/css"),
        }

        if parsed_path.path == "/status":
            data = self.monitor_collection.get_status_json()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(data.encode())
        elif parsed_path.path in files:
            filename, content_type = files[parsed_path.path]
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", content_type)
            self.end_headers()
            self.wfile.write(self.send_file(filename).encode())
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug(f"{self.client_address[0]} - {format % args}")

    def send_file(self, name: str) -> str:
        with open(Path(__file__).parent / "assets" / name) as f:
            return f.read()


class MonitorWebUIServer:
    def __init__(
        self, monitor_collection: monitor.MonitorCollection, port: int
    ) -> None:
        self.monitor_collection = monitor_collection
        self.port = port
        self.server: Optional[http.server.HTTPServer] = None

    def run(self, must_exit_event: threading.Event) -> None:
        def handler(*args: Any, **kwargs: Any) -> MonitorHTTPRequestHandler:
            return MonitorHTTPRequestHandler(self.monitor_collection, *args, **kwargs)

        self.server = http.server.HTTPServer(("localhost", self.port), handler)
        self.server.timeout = 1
        logger.info(f"Serving monitor UI on http://localhost:{self.port}")

        while not must_exit_event.is_set():
            try:
                self.server.handle_request()
            except Exception as e:
                logger.critical(f"Unhandled exception on web server: {e}")
                logger.debug("Exception info", exc_info=True)
                must_exit_event.set()

        self.server.server_close()


def setup_webui(
    configuration: config.Configuration, monitor_collection: monitor.MonitorCollection
) -> Callable[[threading.Event], Any]:
    web_ui_server = MonitorWebUIServer(monitor_collection, configuration.webui_port)
    return web_ui_server.run
