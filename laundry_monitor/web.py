from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
from typing import Callable
from urllib.parse import urlsplit


StatusProvider = Callable[[], dict]
PACKAGE_NAME = "laundry-monitor"


def _service_docs_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Laundry Monitor Service Docs</title>
  <style>
    :root { color-scheme: light dark; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
      margin: 0;
      padding: 2rem;
    }
    main { margin: 0 auto; max-width: 54rem; }
    code, pre {
      font-family: ui-monospace, SFMono-Regular, SFMono-Regular, Consolas, monospace;
    }
    pre, table {
      border: 1px solid color-mix(in oklab, currentColor 18%, transparent);
      border-radius: 8px;
    }
    pre {
      overflow-x: auto;
      padding: 1rem;
    }
    table {
      border-collapse: collapse;
      width: 100%;
    }
    th, td {
      border-bottom: 1px solid color-mix(in oklab, currentColor 14%, transparent);
      padding: 0.75rem;
      text-align: left;
      vertical-align: top;
    }
    th { font-size: 0.95rem; }
    .muted { opacity: 0.8; }
  </style>
</head>
<body>
  <main>
    <h1>Laundry Monitor</h1>
    <p>
      Laundry Monitor watches washer and dryer power sensors, records lifecycle events,
      and sends mobile notifications for washer completion and transfer reminders.
    </p>
    <p class="muted">
      All endpoints are currently public. The service exposes read-only HTTP endpoints;
      appliance notifications and Home Assistant actions happen over the app's outbound Home Assistant connection.
    </p>

    <h2>Endpoints</h2>
    <table>
      <thead>
        <tr><th>Method</th><th>Path</th><th>Purpose</th></tr>
      </thead>
      <tbody>
        <tr><td><code>GET</code></td><td><code>/health</code></td><td><code>GET /health</code> returns the health view of the current service status payload. It returns HTTP 200 when status is <code>ok</code>; otherwise it returns HTTP 503 with the same JSON payload.</td></tr>
        <tr><td><code>GET</code></td><td><code>/v1/status</code></td><td><code>GET /v1/status</code> returns the detailed JSON status payload including appliance freshness, lifecycle summaries, and validation state.</td></tr>
        <tr><td><code>GET</code></td><td><code>/docs</code></td><td><code>GET /docs</code> returns this browser-friendly service documentation page.</td></tr>
        <tr><td><code>GET</code></td><td><code>/openapi.json</code></td><td><code>GET /openapi.json</code> returns the OpenAPI 3.1 description of the public HTTP surface.</td></tr>
      </tbody>
    </table>

    <h2>Quick Checks</h2>
    <pre><code>curl http://127.0.0.1:8102/health
curl http://127.0.0.1:8102/v1/status
curl http://127.0.0.1:8102/openapi.json</code></pre>

    <h2>Notes</h2>
    <ul>
      <li><code>/</code> remains a JSON alias of <code>/health</code> for compatibility.</li>
      <li><code>/health</code> and <code>/v1/status</code> return the same JSON body today; they differ in intent and how homelab tooling uses them.</li>
      <li>There are no inbound protected endpoints in the current app.</li>
    </ul>
  </main>
</body>
</html>
"""


def _openapi_document() -> dict:
    version = "0.1.0"
    try:
        version = metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        pass

    status_schema = {
        "type": "object",
        "description": (
            "Current service status payload produced by the running monitor. "
            "The exact keys may grow as the monitor reports additional lifecycle detail."
        ),
        "required": ["service", "status"],
        "properties": {
            "service": {"type": "string", "const": PACKAGE_NAME},
            "status": {"type": "string"},
        },
        "additionalProperties": True,
    }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Laundry Monitor API",
            "version": version,
            "description": (
                "Read-only HTTP endpoints for homelab health checks and operator-facing status inspection."
            ),
        },
        "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
        "paths": {
            "/": {
                "get": {
                    "summary": "Compatibility health alias",
                    "description": "Returns the same JSON payload as /health.",
                    "responses": _status_responses(status_schema),
                }
            },
            "/health": {
                "get": {
                    "summary": "Service health payload",
                    "description": (
                        "Returns the current status payload. HTTP 200 means the monitor reports status=ok; "
                        "HTTP 503 means the payload reports a degraded or failing state."
                    ),
                    "responses": _status_responses(status_schema),
                }
            },
            "/v1/status": {
                "get": {
                    "summary": "Detailed service status",
                    "description": (
                        "Returns the current status payload, including appliance state, transfer workflow state, "
                        "and lifecycle summaries."
                    ),
                    "responses": _status_responses(status_schema),
                }
            },
            "/docs": {
                "get": {
                    "summary": "Browser-friendly service documentation",
                    "responses": {
                        "200": {
                            "description": "HTML service documentation.",
                            "content": {
                                "text/html": {
                                    "schema": {"type": "string"}
                                }
                            },
                        }
                    },
                }
            },
            "/openapi.json": {
                "get": {
                    "summary": "OpenAPI description",
                    "responses": {
                        "200": {
                            "description": "OpenAPI 3.1 JSON document.",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            },
                        }
                    },
                }
            },
        },
    }


def _status_responses(status_schema: dict) -> dict:
    return {
        "200": {
            "description": "Current status payload with status=ok.",
            "content": {"application/json": {"schema": status_schema}},
        },
        "503": {
            "description": "Current status payload with a degraded or failing status.",
            "content": {"application/json": {"schema": status_schema}},
        },
    }


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
        docs_html = _service_docs_html().encode("utf-8")
        openapi_body = json.dumps(_openapi_document(), sort_keys=True).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = urlsplit(self.path).path
                if path == "/docs":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(docs_html)))
                    self.end_headers()
                    self.wfile.write(docs_html)
                    return
                if path == "/openapi.json":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(openapi_body)))
                    self.end_headers()
                    self.wfile.write(openapi_body)
                    return
                if path not in ("/", "/health", "/v1/status"):
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
