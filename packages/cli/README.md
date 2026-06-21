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
signaldesk providers check
signaldesk ta AMD --provider yfinance --llm none --output json
```

## Provider modes

Default mode:

```bash
signaldesk ta AMD --provider yfinance --llm none --output json
```

Enhanced mode, once richer FMP support is built:

```bash
signaldesk ta AMD --provider fmp --llm none --output json
```

`signaldesk providers list` includes each capability's provider tier, data role, and credential state. The default `yfinance`, local fixture, local CSV, and Stooq paths report tier `default` with credentials `not_required`; FMP, Polygon, and Twelve Data report tier `enhanced` and stay optional. FMP reports `not_configured` until `FMP_API_KEY` is present and `configured` after credentials are available. Default adapters advertise `price`; FMP also advertises enhanced `fundamentals` and `catalyst` capability rows so richer context can be surfaced separately from default TA facts without making paid data required for core workflows.

Future role-specific provider flags may split price, catalyst, fundamentals, and LLM providers.

## Runtime checks

Every CLI-affecting PR should run:

```bash
make check PYTHON=.venv/bin/python
signaldesk --help
signaldesk providers check
```

If the PR changes `ta`, `scan`, or `report`, also run the relevant command and include the output summary in the PR.
