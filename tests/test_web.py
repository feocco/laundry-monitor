from __future__ import annotations

import json
from contextlib import closing
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from laundry_monitor.web import StatusServer


def test_health_and_status_endpoints_keep_existing_payload_and_status_code() -> None:
    payload = {"service": "laundry-monitor", "status": "ok", "appliances": {}}

    with _running_server(payload) as base_url:
        health = _get_json(f"{base_url}/health")
        status = _get_json(f"{base_url}/v1/status")
        root = _get_json(f"{base_url}/")

    assert health["status_code"] == 200
    assert health["body"] == payload
    assert status["status_code"] == 200
    assert status["body"] == payload
    assert root["status_code"] == 200
    assert root["body"] == payload


def test_health_endpoint_keeps_degraded_status_code() -> None:
    payload = {"service": "laundry-monitor", "status": "degraded", "appliances": {}}

    with _running_server(payload) as base_url:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{base_url}/health")

    response = exc_info.value
    body = json.loads(response.read().decode("utf-8"))

    assert response.code == 503
    assert body == payload


def test_docs_endpoint_returns_html_service_docs() -> None:
    payload = {"service": "laundry-monitor", "status": "ok", "appliances": {}}

    with _running_server(payload) as base_url:
        response = _get_text(f"{base_url}/docs")

    assert response["status_code"] == 200
    assert response["content_type"].startswith("text/html")
    assert "Laundry Monitor" in response["body"]
    assert "GET /health" in response["body"]
    assert "GET /v1/status" in response["body"]
    assert "GET /openapi.json" in response["body"]
    assert "All endpoints are currently public" in response["body"]


def test_openapi_endpoint_returns_openapi_3_1_json() -> None:
    payload = {"service": "laundry-monitor", "status": "ok", "appliances": {}}

    with _running_server(payload) as base_url:
        response = _get_json(f"{base_url}/openapi.json")

    assert response["status_code"] == 200
    assert response["content_type"] == "application/json"
    assert response["body"]["openapi"] == "3.1.0"
    assert response["body"]["info"]["title"] == "Laundry Monitor API"
    assert response["body"]["paths"]["/health"]["get"]["responses"]["200"]["description"]
    assert response["body"]["paths"]["/v1/status"]["get"]["responses"]["503"]["description"]
    assert response["body"]["paths"]["/docs"]["get"]["responses"]["200"]["content"]["text/html"]
    assert response["body"]["paths"]["/openapi.json"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]
    assert "security" not in response["body"]


def test_unknown_path_still_returns_404() -> None:
    payload = {"service": "laundry-monitor", "status": "ok", "appliances": {}}

    with _running_server(payload) as base_url:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{base_url}/does-not-exist")

    assert exc_info.value.code == 404


class _running_server:
    def __init__(self, payload: dict) -> None:
        self._server = StatusServer("127.0.0.1", 0, lambda: payload)

    def __enter__(self) -> str:
        self._server.start()
        port = self._server._server.server_address[1]
        return f"http://127.0.0.1:{port}"

    def __exit__(self, exc_type, exc, tb) -> None:
        self._server.stop()


def _get_json(url: str) -> dict:
    with closing(urlopen(url)) as response:
        body = json.loads(response.read().decode("utf-8"))
        return {
            "status_code": response.status,
            "content_type": response.headers["Content-Type"],
            "body": body,
        }


def _get_text(url: str) -> dict:
    with closing(urlopen(url)) as response:
        body = response.read().decode("utf-8")
        return {
            "status_code": response.status,
            "content_type": response.headers["Content-Type"],
            "body": body,
        }
