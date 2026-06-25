import json
from typing import Any
from wsgiref.util import setup_testing_defaults

from signaldesk_api.app import create_app, health_payload, openapi_schema, providers_payload


def _wsgi_response(
    path: str, *, method: str = "GET"
) -> tuple[str, dict[str, Any], list[tuple[str, str]]]:
    status = ""
    headers: list[tuple[str, str]] = []

    def start_response(value: str, response_headers: list[tuple[str, str]]) -> None:
        nonlocal status, headers
        status = value
        headers = response_headers

    environ: dict[str, object] = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    body = b"".join(create_app()(environ, start_response))
    assert ("Content-Type", "application/json; charset=utf-8") in headers
    return status, json.loads(body.decode("utf-8")), headers


def test_health_payload_is_secret_free() -> None:
    payload = health_payload()

    assert payload == {
        "schema_version": "signaldesk.api.health.v1",
        "status": "ok",
        "service": "signaldesk-api",
        "app_env": payload["app_env"],
    }


def test_openapi_schema_documents_health_and_providers() -> None:
    schema = openapi_schema()

    assert schema["openapi"] == "3.1.0"
    assert "/health" in schema["paths"]
    assert "/providers" in schema["paths"]
    assert "/openapi.json" in schema["paths"]
    providers_get = schema["paths"]["/providers"]["get"]
    role_parameter = providers_get["parameters"][0]
    assert role_parameter["name"] == "role"
    assert role_parameter["style"] == "form"
    assert role_parameter["explode"] is True
    assert role_parameter["schema"]["type"] == "array"


def test_providers_payload_uses_backend_registry() -> None:
    payload = providers_payload()

    assert payload["schema_version"] == "signaldesk.api.providers.v1"
    providers = payload["providers"]
    assert isinstance(providers, list)
    assert any(item["provider"] == "local-fixture" and item["available"] for item in providers)
    assert any(item["provider"] == "yfinance" for item in providers)


def test_wsgi_app_routes_json_errors() -> None:
    status, payload, _headers = _wsgi_response("/missing")
    assert status == "404 Not Found"
    assert payload["error"]["type"] == "not_found"

    status, payload, headers = _wsgi_response("/health", method="POST")
    assert status == "405 Method Not Allowed"
    assert payload["error"]["type"] == "method_not_allowed"
    assert ("Allow", "GET") in headers

    status, payload, _headers = _wsgi_response("/missing", method="POST")
    assert status == "404 Not Found"
    assert payload["error"]["type"] == "not_found"



def test_wsgi_app_smoke_serves_health() -> None:
    status, payload, _headers = _wsgi_response("/health")

    assert status == "200 OK"
    assert payload["status"] == "ok"
    assert payload["schema_version"] == "signaldesk.api.health.v1"
