# Persistence, caching, and scheduling

SignalDesk is CLI-first today. Persistence should stay boring and local until runtime workflows prove they need a database, queue, or scheduler. Reports, provider-response caches, and scheduled jobs are separate concerns with different invalidation rules.

## Current durable surface: report artifacts

`signaldesk ta ... --save-dir PATH` and `signaldesk report ... --save-dir PATH` write canonical JSON report artifacts. They preserve the same facts, deterministic signals, risks, provenance, unavailable context, and optional LLM metadata that the runtime command rendered.

A report artifact is an audit/readback object, not a report artifact cache key and not a reusable provider payload. Re-run the CLI command when users want fresh market data, a different provider mode, a different interval, or a different symbol universe.

## Provider-response cache invalidation

A future provider-response cache may speed up repeated scans, but it must not blur data freshness or hide provider failures. Cache keys should include at least:

- provider name and provider role, such as price, fundamentals, or catalyst;
- symbol or watchlist member identity;
- interval and requested date range for candles;
- provider mode, because default and enhanced modes can have different provenance and unavailable-context behavior;
- request shape that changes provider output, such as adjusted/unadjusted price settings when supported;
- SignalDesk/provider adapter schema version when normalized response fields change.

Invalidate or bypass cached provider responses when any key input changes, when the adapter normalization changes, when a user asks for a refresh, or when a configured TTL expires. Until a concrete cache command exists, the safe manual invalidation path is to delete the local cache directory for the affected provider/symbol/date range and rerun the CLI command.

Provider failures are cacheable only as explicit unavailable context with a short TTL. A cached failure must still render as `Unavailable context`; it must never become a silent all-clear or disappear from saved reports.

## Scheduling policy

Scheduling should remain local/manual first. Cron examples should be added only after the report command and artifact readback path are stable for default-mode providers.

Scheduled reports should:

- run the same installed CLI entrypoints as manual usage;
- write canonical JSON artifacts with provider provenance;
- surface non-zero exits and provider unavailable context in logs or notifications;
- avoid paid/enhanced provider requirements for default-mode schedules;
- avoid autonomous PR or issue loops unless product runtime gates remain green.

## Database and queue threshold

Filesystem artifacts and an optional provider-response cache come before SQLite/Postgres or Redis. Add SQLite/Postgres only when workflows need queryable history, report indexing beyond filesystem archive rows, or recoverable multi-step state. Add Redis or a job queue only when scheduling/concurrency needs exceed local cron-style runs.
