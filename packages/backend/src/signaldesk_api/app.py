from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, unquote
from uuid import uuid4

from signaldesk_backend import Settings, default_provider_registry, redact_provider_diagnostic
from signaldesk_backend.providers import MarketDataProvider
from signaldesk_cli.main import MAX_TA_HISTORY_DAYS, _fetch_ta_report

JsonPayload = dict[str, Any]
StartResponse = Callable[[str, list[tuple[str, str]]], None]


class ApiHttpError(Exception):
    def __init__(self, status: str, payload: JsonPayload) -> None:
        super().__init__(payload.get("error", {}).get("message", status))
        self.status = status
        self.payload = payload


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


def _api_request_id() -> str:
    return f"api-request-{uuid4()}"


def _error_payload_with_request_id(payload: JsonPayload, request_id: str) -> JsonPayload:
    error = payload.get("error")
    if not isinstance(error, dict):
        return payload
    return {**payload, "error": {**error, "request_id": request_id}}


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


def _planned_endpoint_unavailable(path: str) -> JsonPayload:
    return {
        "error": {
            "type": "not_implemented",
            "message": (
                f"SignalDesk API route {path} is planned but not implemented yet; "
                "use CLI workflows until the shared deterministic backend workflow exists"
            ),
        },
        "unavailable_context": [
            {
                "context_type": "api_route",
                "reason": "planned_endpoint_not_implemented",
                "route": path,
            }
        ],
    }


def _error_payload(error_type: str, message: str, *, field: str | None = None) -> JsonPayload:
    error: JsonPayload = {
        "type": error_type,
        "message": message,
    }
    if field is not None:
        error["field"] = field
    return {"error": error}


def _validation_error(field: str, message: str) -> ApiHttpError:
    return ApiHttpError(
        "400 Bad Request",
        _error_payload("validation_error", message, field=field),
    )


def _first_query_value(
    query: dict[str, list[str]], field: str, default: str | None = None
) -> str | None:
    values = query.get(field)
    if not values:
        return default
    return values[-1]


def _parse_days(query: dict[str, list[str]]) -> int:
    raw_days = _first_query_value(query, "days", "120")
    assert raw_days is not None
    try:
        days = int(raw_days)
    except ValueError as exc:
        raise _validation_error("days", "days must be an integer") from exc
    if days < 1:
        raise _validation_error("days", "days must be greater than or equal to 1")
    if days > MAX_TA_HISTORY_DAYS:
        raise _validation_error(
            "days", f"days must be less than or equal to {MAX_TA_HISTORY_DAYS}"
        )
    return days


def _symbol_ta_payload(symbol: str, query: dict[str, list[str]]) -> JsonPayload:
    if not symbol.strip():
        raise _validation_error("symbol", "symbol is required")
    llm = (_first_query_value(query, "llm", "none") or "none").strip().lower()
    if llm != "none":
        raise _validation_error(
            "llm",
            "API TA currently supports llm=none only; enhanced LLM narration is unavailable",
        )
    provider = _first_query_value(query, "provider")
    mode = _first_query_value(query, "mode", "default") or "default"
    interval = _first_query_value(query, "interval", "1d") or "1d"
    days = _parse_days(query)
    try:
        return _fetch_ta_report(
            default_provider_registry(),
            symbol=symbol,
            provider=provider,
            mode=mode,
            interval=interval,
            days=days,
            as_of=datetime.now(UTC),
            llm_provider=llm,
        )
    except (KeyError, ValueError) as exc:
        raise ApiHttpError(
            "400 Bad Request",
            _error_payload("validation_error", str(exc)),
        ) from exc
    except RuntimeError as exc:
        raise ApiHttpError(
            "502 Bad Gateway",
            _error_payload("provider_error", redact_provider_diagnostic(str(exc))),
        ) from exc


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


def _parameter(
    name: str,
    location: str,
    description: str,
    schema: JsonPayload,
    *,
    required: bool = False,
) -> JsonPayload:
    return {
        "name": name,
        "in": location,
        "required": required,
        "description": description,
        "schema": schema,
    }


def openapi_schema() -> JsonPayload:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "SignalDesk API",
            "version": "0.1.0",
            "description": (
                "TA-first market intelligence API exposing health, provider metadata, "
                "and canonical technical-analysis payloads."
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
                            "style": "form",
                            "explode": True,
                            "schema": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
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
            "/symbols/{symbol}/ta": {
                "get": {
                    "summary": "Canonical technical-analysis report",
                    "description": (
                        "Returns the same signaldesk.ta.v1 JSON contract as the CLI "
                        "technical-analysis command. Analysis is delegated to the shared "
                        "deterministic TA path; API code does not invent market facts."
                    ),
                    "parameters": [
                        _parameter(
                            "symbol",
                            "path",
                            "Ticker symbol to analyze.",
                            {"type": "string", "minLength": 1},
                            required=True,
                        ),
                        _parameter(
                            "provider",
                            "query",
                            (
                                "Optional explicit price provider, for example "
                                "local-fixture or yfinance."
                            ),
                            {"type": "string"},
                        ),
                        _parameter(
                            "mode",
                            "query",
                            "Provider role mode when provider is omitted: default or enhanced.",
                            {"type": "string", "default": "default"},
                        ),
                        _parameter(
                            "interval",
                            "query",
                            "Historical candle interval.",
                            {"type": "string", "default": "1d"},
                        ),
                        _parameter(
                            "days",
                            "query",
                            "Number of calendar days of history to request.",
                            {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_TA_HISTORY_DAYS,
                                "default": 120,
                            },
                        ),
                        _parameter(
                            "llm",
                            "query",
                            "LLM narrative mode. The API currently supports none only.",
                            {"type": "string", "enum": ["none"], "default": "none"},
                        ),
                    ],
                    "responses": {
                        "200": {
                            "description": "Canonical signaldesk.ta.v1 technical-analysis payload",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        },
                        "400": {"description": "Typed validation error"},
                        "502": {"description": "Provider unavailable or returned no candles"},
                    },
                }
            },
            "/scan": {
                "get": {
                    "summary": "Watchlist scan status",
                    "description": (
                        "Planned route for scan workflows. It currently returns a typed "
                        "not_implemented error instead of duplicating scan logic in the API layer."
                    ),
                    "responses": {
                        "501": {
                            "description": "Scan workflow is not implemented in the API yet",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/reports": {
                "get": {
                    "summary": "Report generation status",
                    "description": (
                        "Planned route for report workflows. It currently returns a typed "
                        "not_implemented error until reports are backed by shared "
                        "deterministic code."
                    ),
                    "responses": {
                        "501": {
                            "description": "Report workflow is not implemented in the API yet",
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


def _symbol_ta_path_symbol(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) == 3 and parts[0] == "symbols" and parts[2] == "ta":
        return unquote(parts[1])
    return None


class SignalDeskApiApp:
    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        request_id = _api_request_id()

        def respond(
            status: str,
            payload: JsonPayload,
            *,
            extra_headers: list[tuple[str, str]] | None = None,
        ) -> list[bytes]:
            response_payload = payload
            if not status.startswith(("200", "201", "204")):
                response_payload = _error_payload_with_request_id(payload, request_id)
            headers = [("X-SignalDesk-Request-Id", request_id)]
            headers.extend(extra_headers or [])
            return _json_response(
                start_response,
                status,
                response_payload,
                extra_headers=headers,
            )

        is_known_path = path in {"/health", "/providers", "/scan", "/reports", "/openapi.json"}
        ta_symbol = _symbol_ta_path_symbol(path)
        if not is_known_path and ta_symbol is None:
            return respond("404 Not Found", _not_found(path))
        if method != "GET":
            return respond(
                "405 Method Not Allowed",
                _method_not_allowed(method),
                extra_headers=[("Allow", "GET")],
            )
        query = parse_qs(str(environ.get("QUERY_STRING", "")))
        if path == "/health":
            return respond("200 OK", health_payload())
        if path == "/providers":
            payload = providers_payload()
            if "role" in query:
                roles = {role.strip().lower() for role in query["role"] if role.strip()}
                payload["providers"] = [
                    item for item in payload["providers"] if item.get("data_role") in roles
                ]
            return respond("200 OK", payload)
        if path in {"/scan", "/reports"}:
            return respond("501 Not Implemented", _planned_endpoint_unavailable(path))
        if ta_symbol is not None:
            try:
                return respond("200 OK", _symbol_ta_payload(ta_symbol, query))
            except ApiHttpError as exc:
                return respond(exc.status, exc.payload)
        return respond("200 OK", openapi_schema())


def create_app() -> SignalDeskApiApp:
    return SignalDeskApiApp()
