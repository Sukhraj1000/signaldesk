# Observability and error taxonomy

SignalDesk keeps runtime failures actionable without exposing credentials. Provider failures can include a stable `error_code`, `error_category`, and `retryable` flag while preserving the existing human-readable `error` message.

Initial provider taxonomy values:

| Code | Category | Retryable | Meaning |
|---|---|---:|---|
| `provider_error` | `provider` | false | Generic provider failure when no narrower code is known. |
| `rate_limited` | `rate_limit` | true | Provider throttling or HTTP 429-style response. |
| `transport_error` | `transport` | true | Network, timeout, DNS, or connection failure before a provider payload is available. |

Provider diagnostics must pass through `redact_provider_diagnostic` before reaching CLI, API, logs, warnings, or unavailable context. Missing provider data remains explicit unavailable context rather than being silently omitted.
