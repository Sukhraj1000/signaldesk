# CLI JSON contract

`signaldesk ta <SYMBOL> --llm none --output json` emits a versioned JSON object for deterministic technical analysis. When `--provider` is omitted, the command resolves the price provider from `--mode default|enhanced`; an explicit `--provider <provider>` still overrides role-mode resolution for targeted smoke checks.

The current schema is `signaldesk.ta.v1`. It keeps backward-compatible top-level fields for early CLI consumers, but the durable contract is grouped by category so downstream tools do not confuse facts, deterministic signals, risk framing, provenance, unavailable context, or optional narrative.

## Top-level contract sections

- `schema_version`: schema identifier for the CLI TA JSON object.
- `facts`: directly observed or request-scoped facts, such as symbol, provider, interval, candle count, latest timestamp, and latest close.
- `provider_mode`: resolved provider-role metadata for the run, including mode, price provider, optional fundamentals provider, optional catalyst provider, and optional LLM provider.
- `deterministic_signals`: values calculated by SignalDesk deterministic code from the candle series. This currently includes indicators, regimes, deterministic technical events, swing levels, confirmation level, and invalidation level.
- `risks`: deterministic risk or scope notes with `kind`, `severity`, `message`, and `source`. The TA path currently flags scope limits, insufficient history, unknown regimes, missing invalidation levels, unavailable enhanced context, high volatility, low-volume/liquidity, trend conflicts, and overextension events from already-computed facts. Missing enhanced data must not be interpreted as no risk.
- `scores`: deterministic `setup_quality`, `risk`, and `data_quality` scores bounded from 0 to 100, each with traceable reason codes, source rules, messages, and weights. Decimal values are serialized as strings, matching the rest of the TA JSON contract.
- `provenance`: provider/source/timeframe/input metadata for the data used to compute the output.
- `unavailable_context`: context that is unavailable in the current mode, such as fundamentals in the default TA path or LLM narrative when `--llm none` is selected.
- `llm` and `narrative`: LLM mode metadata. Narrative is `null` until guarded LLM explanation mode is implemented.

## Provider mode behavior

Default mode remains useful without paid keys. Enhanced provider or LLM fields must be optional, fixture-backed in tests, or reported as unavailable context rather than silently omitted.

The golden CLI test in `tests/test_cli.py` protects the current `signaldesk.ta.v1` shape with fixture-backed data, so CI does not require live provider network or paid credentials.

## TA Markdown report

`signaldesk ta <SYMBOL> --llm none --output markdown` renders a compact human-readable report from the same canonical `signal_card` object used by JSON output. The Markdown report separates facts, deterministic signals, risks, unavailable context, provenance, and optional narrative state. It includes the generated timestamp, price provider, latest observed close, explicit missing enhanced/LLM context, and provider/source/timeframe/input provenance without introducing LLM-derived facts or extra provider data.


The machine-readable schema for the canonical signal-card envelope lives at [`docs/schemas/signaldesk.ta.v1.schema.json`](schemas/signaldesk.ta.v1.schema.json). It is intentionally limited to the durable renderer-facing sections and keeps early flat compatibility fields as additional top-level properties.

## Signal-card section aliases

The v1 JSON keeps early flat and grouped fields for compatibility, then adds canonical signal-card sections so future CLI/API/dashboard/reporting renderers can share one object:

- `identity`: symbol, timeframe, generated timestamp, and schema version.
- `trend`: moving-average, momentum, and regime summaries from deterministic calculations.
- `levels`: support, resistance, Fibonacci placeholder, confirmation, and invalidation fields.
- `events`: deterministic event list; mirrors `technical_events`.
- `risk`: deterministic flags and unavailable context together for card rendering.
- `score`: deterministic score breakdowns for setup quality, risk, and data quality.
- `signal_card`: one canonical nested card object that groups `identity`, `provider_mode`, `facts`, `trend`, `levels`, `events`, `risk`, `score`, `provenance`, `unavailable_context`, and LLM narrative metadata for renderers that should consume a single object.

The canonical aliases do not introduce new data sources or LLM-derived facts; they regroup already-computed deterministic output and unavailable-context metadata. The top-level compatibility fields remain available while downstream adapters migrate to `signal_card`.


## Watchlist scan JSON

`signaldesk scan --watchlist <path> --output json` emits a deterministic watchlist scan payload for ranked multi-symbol TA workflows. The payload is assembled from the same canonical TA signal-card summaries as `signaldesk ta`; the scan command does not introduce separate market-data facts or LLM-derived conclusions.

The scan JSON object includes:

- `watchlist`: source watchlist path.
- `watchlist_model`: normalized watchlist metadata (`name`, `symbols`, `tags`, `asset_class`, `provider_preference`, `enabled`, and `notes`).
- `scanned_at`: UTC scan timestamp shared by all symbols in the run.
- `provider_mode`: resolved role/provider metadata, including unavailable enhanced context where relevant.
- `symbols`: normalized, de-duplicated requested symbols in watchlist order.
- `results`: per-symbol outcomes in watchlist order. Successful rows have `status: "ok"` plus a deterministic `summary`; failures have `status: "failed"` plus a redacted `error`; disabled watchlists return `status: "skipped"` rows with a reason.
- `ranked_setups`: successful results sorted deterministically by setup quality, risk score, then symbol, each with a `rank`.
- `failed_symbols`: all failed symbol rows, preserving watchlist order so one bad symbol does not hide the rest of the scan.
- `skipped_symbols`: skipped rows, currently used when the normalized watchlist is disabled.

Default scan mode remains usable without paid keys. For no-network fixture smoke checks, use a watchlist whose `provider_preference` is `local-fixture` or pass `--provider local-fixture`; missing enhanced context must appear as unavailable context rather than being interpreted as absent risk.

## Watchlist report JSON

`signaldesk report --watchlist <path> --format json` emits the same deterministic watchlist payload used by the Markdown report renderer. The JSON object includes `watchlist`, `watchlist_model`, `scanned_at`, `provider_mode`, requested `symbols`, `results`, `ranked_setups`, `failed_symbols`, and `skipped_symbols`. Successful results include a `summary` with provider, deterministic TA summary fields, provenance, and unavailable context; failed results include a redacted `error` string. This keeps report automation machine-readable without introducing extra data sources or LLM-derived facts.
