# Persistence, caching, and scheduling

SignalDesk is CLI-first today. Persistence should stay boring and local until runtime workflows prove they need a database, queue, or scheduler. Reports, provider-response caches, and scheduled jobs are separate concerns with different invalidation rules.

## Current durable surface: report artifacts

`signaldesk ta ... --save-dir PATH` and `signaldesk report ... --save-dir PATH` write canonical JSON report artifacts. They preserve the same facts, deterministic signals, risks, provenance, unavailable context, and optional LLM metadata that the runtime command rendered.

A report artifact is an audit/readback object, not a report artifact cache key and not a reusable provider payload. Re-run the CLI command when users want fresh market data, a different provider mode, a different interval, or a different symbol universe.

## Provider-response cache invalidation

`signaldesk ta`, `signaldesk scan`, and `signaldesk report` accept `--cache-dir PATH` to cache normalized historical candle provider responses on the local filesystem. Use `--refresh-cache` to bypass a matching entry and replace it with a fresh provider fetch. The cache is a provider-response cache, not a report artifact: saved reports remain canonical readback artifacts and should not be reused as market-data payloads.

A provider-response cache may speed up repeated scans, but it must not blur data freshness or hide provider failures. Cache keys should include at least:

- provider name and provider role, such as price, fundamentals, or catalyst;
- symbol or watchlist member identity;
- interval and requested date range for candles;
- provider mode, because default and enhanced modes can have different provenance and unavailable-context behavior;
- request shape that changes provider output, such as adjusted/unadjusted price settings when supported;
- SignalDesk/provider adapter schema version when normalized response fields change.

Invalidate or bypass cached provider responses when any key input changes, when the adapter normalization changes, when a user asks for a refresh, or when a configured TTL expires. The safe manual invalidation path is to delete the entire local provider-cache namespace for the affected provider role, or explicitly purge every matching provider, symbol, interval, date range, provider mode, request shape, and adapter schema-version entry before rerunning the CLI command.

Provider failures are cacheable only as explicit unavailable context with a short TTL. A cached failure must still render as `Unavailable context`; it must never become a silent all-clear or disappear from saved reports.

## Scheduling policy

Scheduling remains local/manual first. Default-mode schedules should use the same installed CLI entrypoints that a user can run by hand, write canonical artifacts, and capture both stdout and stderr so provider failures are visible in the job log.

A minimal default-mode cron entry can keep the core workflow recoverable without requiring paid provider keys:

```cron
# Run a weekday after-market report with open/default providers only.
# stdout contains the rendered report; stderr contains provider/cache/save failures.
5 21 * * 1-5 cd /path/to/signaldesk && \
  .venv/bin/signaldesk report \
    --watchlist watchlists/default.yaml \
    --mode default \
    --llm none \
    --format json \
    --save-dir reports/daily \
    --cache-dir .signaldesk-cache/provider-responses \
    >> logs/signaldesk-report.log 2>&1
```

Scheduled reports should:

- run the same installed CLI entrypoints as manual usage;
- write canonical JSON artifacts with provider provenance;
- keep cache and report directories separate because provider responses are reusable inputs while report artifacts are audit/readback outputs;
- capture command output and non-zero exits in a durable log;
- inspect saved JSON for `unavailable_context` entries before treating a run as complete;
- avoid paid/enhanced provider requirements for default-mode schedules;
- avoid autonomous PR or issue loops unless product runtime gates remain green.

A simple local follow-up check can fail a shell wrapper when any saved report contains unavailable context:

```bash
python - <<PY
import json
import pathlib
import sys

reports_dir = pathlib.Path("reports/daily")
latest = max(reports_dir.glob("*.json"), key=lambda path: path.stat().st_mtime)
payload = json.loads(latest.read_text(encoding="utf-8"))
results = payload.get("results") or [payload]
missing = []
for result in results:
    card = result.get("signal_card") or result.get("summary", {}).get("signal_card") or {}
    summary = result.get("summary") or {}
    missing.extend(card.get("unavailable_context") or [])
    missing.extend(summary.get("unavailable_context") or [])
if missing:
    print(f"{latest}: unavailable context: {missing}", file=sys.stderr)
    sys.exit(1)
print(f"{latest}: no unavailable context")
PY
```

## Database and queue threshold

Filesystem artifacts and an optional provider-response cache come before SQLite/Postgres or Redis. Add SQLite/Postgres only when workflows need queryable history, report indexing beyond filesystem archive rows, or recoverable multi-step state. Add Redis or a job queue only when scheduling/concurrency needs exceed local cron-style runs.
