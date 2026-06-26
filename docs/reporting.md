# Reporting and data presentation

SignalDesk reports are renderers over canonical signal-card objects. The backend remains the source of truth for market facts, deterministic technical signals, levels, risk flags, scores, provenance, unavailable context, and optional LLM metadata. CLI, API, dashboard, and future export surfaces should not recalculate those values or blend categories together.

## Current report surfaces

- `signaldesk ta SYMBOL --output json` emits the full `signaldesk.ta.v1` payload, including the nested `signal_card` object and compatibility aliases. Add `--save-dir PATH` to save the same canonical JSON as a filesystem artifact that can be read back by archive tooling.
- `signaldesk ta SYMBOL --output table` emits a compact tab-separated view for terminals.
- `signaldesk ta SYMBOL --output markdown` emits a readable single-symbol Markdown report.
- `signaldesk scan --watchlist PATH --output json` emits a `signaldesk.watchlist_report.v1` payload with per-symbol summaries that retain each canonical `signal_card`.
- `signaldesk report --watchlist PATH --format markdown` emits a watchlist Markdown report from the same schema-versioned scan payload.
- `signaldesk report --watchlist PATH --format table` emits a compact terminal table from the same schema-versioned scan payload.
- `signaldesk report --watchlist PATH --format json` emits the same `signaldesk.watchlist_report.v1` payload, including top-level report provenance for successful symbols. Add `--save-dir PATH` to save the canonical watchlist report JSON artifact.

Default-mode examples should work without paid keys by using `yfinance`, `local-fixture`, or `local-csv` providers. Enhanced providers such as FMP may add richer context when credentials are available, but missing enhanced context must remain explicit unavailable context.


## Filesystem report artifacts

`--save-dir` writes the canonical JSON payload before terminal rendering, so the saved artifact is the same deterministic object used by JSON output and downstream archive readers. Artifact filenames include the report type, subject, and generated timestamp. Treat filenames as convenience labels only; consumers should read the JSON schema/version fields from the file contents.

Saved single-symbol TA artifacts can be read back with `signaldesk web report-archive --reports-dir PATH --output json`, which validates required canonical sections before building dashboard-facing archive rows. Watchlist report artifacts use `signaldesk.watchlist_report.v1` and are intended for direct JSON/Markdown/table readback rather than TA archive rows.

Provider failures and missing enhanced/LLM context must remain explicit in the saved JSON. A saved report artifact is not a data cache: rerun the command to refresh market data, and delete or replace old artifacts when provider inputs, symbol lists, intervals, date ranges, or provider modes change.

## Required report sections

Human-readable reports should include an explicit **Report boundaries** note that says facts, deterministic signals, risks, unavailable context, and optional narrative are rendered separately; missing enhanced provider or LLM context is unavailable context, not a silent all-clear; and reports are not investment advice or trade execution instructions.

Human-readable reports should keep these sections separate:

1. **Facts**: symbol, timeframe, provider, timestamps, latest close, candle count, and schema version.
2. **Setup**: a compact answer to what the setup is and why it matters.
3. **Deterministic signals**: trend/volume/volatility regimes, confirmation and invalidation levels, technical events, and score reasons derived by deterministic code.
4. **Risks**: risk flags and confidence reducers.
5. **Unavailable context**: missing fundamentals, catalysts, enhanced provider data, or disabled LLM narrative.
6. **Provenance**: provider, source, timeframe, inputs, generation timestamp, and observation count.
7. **Optional narrative**: LLM state and narrative only when available; `--llm none` must render narrative as unavailable.

Reports should answer:

- what is the setup?
- why does it matter?
- what confirms it?
- what invalidates it?
- what risks or missing data reduce confidence?

## Renderer contract

Renderers should call `extract_ta_signal_card(report)` before formatting. This validates that the nested `signal_card` matches the top-level aliases and prevents presentation layers from accidentally rendering stale or drifted sections.

When adding a new renderer:

- render from `signal_card`, not from provider payloads or raw indicators;
- keep provider/enhanced context separate from technical facts;
- print unavailable context rather than dropping missing data;
- keep Markdown/table output compact and avoid raw indicator dumps;
- include runtime evidence for the affected command in the PR body.

## Runtime smoke examples

```bash
signaldesk ta AMD --provider local-fixture --llm none --output markdown
signaldesk ta AMD --provider local-fixture --llm none --output json --save-dir /tmp/signaldesk-reports
signaldesk web report-archive --reports-dir /tmp/signaldesk-reports --output json
signaldesk ta AMD --provider local-fixture --llm none --output table
signaldesk report --watchlist watchlists/default.yaml --provider local-fixture --format markdown
signaldesk report --watchlist watchlists/default.yaml --provider local-fixture --format table
```

For live default-mode checks, use `--provider yfinance` when network access is allowed. Paid/enhanced provider checks should be reported separately and must not be required for the default TA workflow.
