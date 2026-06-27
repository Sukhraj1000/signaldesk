# SignalDesk CLI

The CLI package provides the `signaldesk` command-line interface. It is the first product surface and the main runtime smoke target for CI.

## CLI principles

- CLI commands orchestrate backend services; they should not contain core TA logic.
- JSON output should be stable and machine-readable.
- Human-readable table/Markdown output should render canonical backend objects.
- Errors go to stderr and must not expose secrets.
- Default mode should work without paid keys.
- Enhanced mode should clearly report missing credentials or unavailable context.

## Current commands

```bash
signaldesk --help
signaldesk health
signaldesk providers list
signaldesk providers mode
signaldesk providers check
signaldesk ta AMD --llm none --output json
signaldesk scan --watchlist watchlists/default.yaml --provider local-fixture --max-workers 4 --output json
signaldesk report --watchlist watchlists/default.yaml --provider local-fixture --format json
signaldesk fixtures generate --symbol AMD --output-dir fixtures/local --output json
signaldesk backtest setup AMD --setup-label breakout_watch --signal-index 10 --horizon 5 --provider local-fixture --output json
signaldesk backtest setup AMD --setup-label breakout_watch --signal-index 10 --horizon 5 --provider local-fixture --output markdown
signaldesk backtest setup-labels --output json
signaldesk backtest setup-batch AMD --horizon 1 --horizon 5 --provider local-fixture --output json
```

## Provider modes

Default mode uses `yfinance` for price data when `--provider` is omitted:

```bash
signaldesk ta AMD --llm none --output json
signaldesk scan --watchlist watchlists/default.yaml --provider local-fixture --max-workers 4 --output json
```


Watchlist scan/report commands fetch symbols with bounded concurrency. Use `--max-workers`
(1-16, default 4) to tune parallel price fetches while keeping ranked output deterministic
and preserving failed/skipped symbols in the payload.

The provider can still be passed explicitly for reproducible live checks:

```bash
signaldesk ta AMD --provider yfinance --llm none --output json
```

Enhanced mode, once richer FMP support is built:

```bash
signaldesk ta AMD --provider fmp --llm none --output json
```

`signaldesk providers list` includes each capability's provider tier, data role, credential state, supported intervals, max history/rate-limit metadata when an adapter declares it, and whether the capability is suitable for safe health/live checks. The default `yfinance`, local fixture, and Stooq paths report tier `default` with credentials `not_required`; FMP, Polygon, and Twelve Data report tier `enhanced` and stay optional. FMP reports `not_configured` until `FMP_API_KEY` is present and `configured` after credentials are available. Default adapters advertise `price`; FMP also advertises enhanced `fundamentals` and `catalyst` capability rows so richer context can be surfaced separately from default TA facts without making paid data required for core workflows. Use `signaldesk providers list --tier default`, `signaldesk providers list --tier enhanced`, `signaldesk providers list --role fundamentals --output json`, `signaldesk providers list --credential-state not_configured`, or `signaldesk providers list --live-check-only` to inspect provider capabilities without mixing default price capabilities with enhanced context capabilities.

`signaldesk providers mode` resolves the role-provider selection that higher-level signal cards can reuse without making network calls. Default mode selects `yfinance` for price data and leaves enhanced roles unavailable. `signaldesk providers mode --mode enhanced --output json` selects FMP roles only when credentials are configured; otherwise it keeps default yfinance price data and reports FMP fundamentals/catalysts as unavailable context.

Provider role resolution can be configured with optional environment variables without changing the default open-data path:

- `SIGNALDESK_DEFAULT_PRICE_PROVIDER`
- `SIGNALDESK_ENHANCED_PRICE_PROVIDER`
- `SIGNALDESK_ENHANCED_FUNDAMENTALS_PROVIDER`
- `SIGNALDESK_ENHANCED_CATALYST_PROVIDER`

Each configured provider must be registered, advertise the requested role, and be usable without missing credentials. Unusable default price preferences fail fast as configuration errors; unusable enhanced role preferences are reported as unavailable context and default price data still falls back to the configured default/yfinance path.

`signaldesk providers check` stays safe by avoiding live network probes for providers whose capabilities mark `live_check=false`. Stooq is no-key and default-tier, but its health row reports `not checked` because public endpoint availability is proven only when a candle fetch runs. Use `signaldesk providers check --output json` for machine-readable status rows shaped as `provider`, `status`, `result`, and `warnings`; diagnostic text is redacted before it is printed.

Enhanced signal-card behavior is documented in `../../docs/enhanced-context.md`. Future provider configuration can build on these resolved roles to split price, catalyst, fundamentals, and LLM providers.

`signaldesk fixtures generate` writes deterministic `local-csv` compatible OHLCV CSV files for demos, docs, and no-network provider experiments without committing live market-data dumps. Use `--output json` for machine-readable file paths and row counts.

`signaldesk backtest setup` replays already-labeled deterministic setup points over historical candles and emits `signaldesk.backtest.setup_replay.v1`. The command defaults to `local-fixture` in default mode so the core backtest smoke path remains useful without paid keys or network access. Reports include JSON, table, and Markdown output with metrics, provenance, limitations, and unavailable forward-window context, but intentionally exclude broker, order, fill, position-sizing, slippage, recommendation, and live-trading fields. The machine-readable schema lives at [`../../docs/schemas/signaldesk.backtest.setup_replay.v1.schema.json`](../../docs/schemas/signaldesk.backtest.setup_replay.v1.schema.json). `signaldesk backtest setup-batch` evaluates every built-in deterministic setup label against one shared candle history and emits `signaldesk.backtest.setup_batch.v1`, preserving `evaluated`, `no_signals`, and `insufficient_history` status per label. See [`../../docs/backtesting-evaluation.md`](../../docs/backtesting-evaluation.md) for the default-mode metrics, walk-forward window behavior, and research-only limitations.

`signaldesk scan --watchlist watchlists/default.yaml` reads a small YAML watchlist with a top-level `symbols:` list and renders deterministic TA summaries for each symbol from the same canonical signal-card object used by `signaldesk ta`. Use `--output json` for machine-readable summaries that preserve provider/provenance and unavailable context. For no-network smoke checks, run with `--provider local-fixture` or set `SIGNALDESK_DEFAULT_PRICE_PROVIDER=local-fixture`.


## Reporting outputs

`signaldesk ta` supports `--output json`, `--output table`, and `--output markdown`. JSON keeps the full canonical `signal_card`; table and Markdown render compact human-readable views from that same object. `signaldesk report --watchlist ... --format markdown` uses the scan payload to render watchlist-level signal cards without re-running analysis logic.

Markdown reports include generation timestamp, schema version, provenance, unavailable context, deterministic setup/confirmation/invalidation details, risks, and optional narrative state. See `../../docs/reporting.md` for the renderer contract.

```bash
signaldesk ta AMD --provider local-fixture --llm none --output markdown
signaldesk report --watchlist watchlists/default.yaml --provider local-fixture --format markdown
```

## Runtime checks

Every CLI-affecting PR should run:

```bash
make check PYTHON=.venv/bin/python
signaldesk --help
signaldesk providers check
```

`signaldesk report --watchlist watchlists/default.yaml --format markdown` renders the same fixture-backed scan payload as a human-readable report. Use `--format json` for the machine-readable report payload, including per-symbol provenance and unavailable context.

If the PR changes `ta`, `scan`, or `report`, also run the relevant command and include the output summary in the PR.
