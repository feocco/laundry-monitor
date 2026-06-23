from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


StatusProvider = Callable[[], dict]


class StatusServer:
    def __init__(self, host: str, port: int, status_provider: StatusProvider) -> None:
        self.host = host
        self.port = port
        self.status_provider = status_provider
        self._server = self._build_server()
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _build_server(self) -> ThreadingHTTPServer:
        provider = self.status_provider

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path not in ("/", "/health", "/v1/status"):
                    self.send_error(404)
                    return
                payload = provider()
                status = 200 if payload.get("status") == "ok" else 503
                body = json.dumps(payload, sort_keys=True).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        return ThreadingHTTPServer((self.host, self.port), Handler)
