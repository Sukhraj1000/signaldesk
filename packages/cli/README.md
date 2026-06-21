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
```

## Provider modes

Default mode uses `yfinance` for price data when `--provider` is omitted:

```bash
signaldesk ta AMD --llm none --output json
```

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

`signaldesk providers check` stays safe by avoiding live network probes for providers whose capabilities mark `live_check=false`. Stooq is no-key and default-tier, but its health row reports `not checked` because public endpoint availability is proven only when a candle fetch runs. Use `signaldesk providers check --output json` for machine-readable status rows shaped as `provider`, `status`, `result`, and `warnings`; diagnostic text is redacted before it is printed.

Future provider configuration can build on these resolved roles to split price, catalyst, fundamentals, and LLM providers.

## Runtime checks

Every CLI-affecting PR should run:

```bash
make check PYTHON=.venv/bin/python
signaldesk --help
signaldesk providers check
```

If the PR changes `ta`, `scan`, or `report`, also run the relevant command and include the output summary in the PR.
