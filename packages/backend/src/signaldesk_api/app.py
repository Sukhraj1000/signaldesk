from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import asdict
from typing import Any
from urllib.parse import parse_qs

from signaldesk_backend import Settings, default_provider_registry, redact_provider_diagnostic
from signaldesk_backend.providers import MarketDataProvider

JsonPayload = dict[str, Any]
StartResponse = Callable[[str, list[tuple[str, str]]], None]


def _json_response(
    start_response: StartResponse,
    status: str,
    payload: JsonPayload,
    *,
    extra_headers: list[tuple[str, str]] | None = None,
) -> list[bytes]:
    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ]
    headers.extend(extra_headers or [])
    start_response(status, headers)
    return [body]


def _not_found(path: str) -> JsonPayload:
    return {
        "error": {
            "type": "not_found",
            "message": f"No SignalDesk API route is registered for {path}",
        }
    }


def _method_not_allowed(method: str) -> JsonPayload:
    return {
        "error": {
            "type": "method_not_allowed",
            "message": f"SignalDesk API route does not allow {method}",
        }
    }


def health_payload() -> JsonPayload:
    settings = Settings.from_env()
    return {
        "schema_version": "signaldesk.api.health.v1",
        "status": "ok",
        "service": "signaldesk-api",
        "app_env": settings.app_env,
    }


def _provider_capability_payload(provider: MarketDataProvider) -> list[JsonPayload]:
    try:
        capabilities = provider.capabilities()
    except Exception as exc:
        return [
            {
                "provider": provider.name,
                "available": False,
                "unavailable_context": {
                    "context_type": "provider_capabilities",
                    "reason": redact_provider_diagnostic(f"{type(exc).__name__}: {exc}"),
                },
            }
        ]
    return [asdict(capability) | {"available": True} for capability in capabilities]


def providers_payload() -> JsonPayload:
    registry = default_provider_registry()
    providers = sorted(registry.list(), key=lambda provider: provider.name)
    return {
        "schema_version": "signaldesk.api.providers.v1",
        "providers": [
            capability
            for provider in providers
            for capability in _provider_capability_payload(provider)
        ],
    }


def openapi_schema() -> JsonPayload:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "SignalDesk API",
            "version": "0.1.0",
            "description": (
                "TA-first market intelligence API exposing health and provider metadata."
            ),
        },
        "paths": {
            "/health": {
                "get": {
                    "summary": "Service health",
                    "responses": {
                        "200": {
                            "description": "SignalDesk API is reachable",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/providers": {
                "get": {
                    "summary": "Provider capabilities",
                    "parameters": [
                        {
                            "name": "role",
                            "in": "query",
                            "required": False,
                            "description": (
                                "Optional provider data role filter such as price, "
                                "fundamentals, or catalyst. Repeat the parameter "
                                "to request multiple roles."
                            ),
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Configured provider capability metadata",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/openapi.json": {
                "get": {
                    "summary": "OpenAPI document",
                    "responses": {
                        "200": {
                            "description": "OpenAPI schema for SignalDesk API",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
        },
    }


class SignalDeskApiApp:
    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        if path not in {"/health", "/providers", "/openapi.json"}:
            return _json_response(start_response, "404 Not Found", _not_found(path))
        if method != "GET":
            return _json_response(
                start_response,
                "405 Method Not Allowed",
                _method_not_allowed(method),
                extra_headers=[("Allow", "GET")],
            )
        if path == "/health":
            return _json_response(start_response, "200 OK", health_payload())
        if path == "/providers":
            query = parse_qs(str(environ.get("QUERY_STRING", "")))
            payload = providers_payload()
            if "role" in query:
                roles = {role.strip().lower() for role in query["role"] if role.strip()}
                payload["providers"] = [
                    item for item in payload["providers"] if item.get("data_role") in roles
                ]
            return _json_response(start_response, "200 OK", payload)
        return _json_response(start_response, "200 OK", openapi_schema())


def create_app() -> SignalDeskApiApp:
    return SignalDeskApiApp()
