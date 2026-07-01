# Enhanced catalyst and fundamental context

SignalDesk is TA-first in default mode. Enhanced context adds provider-sourced company facts and catalysts when a richer adapter such as FMP is configured, but it does not change the deterministic technical-analysis source of truth.

## Provider-mode behavior

- `signaldesk ta <SYMBOL> --mode default --llm none --output json` keeps price data on the default open-data provider, normally `yfinance`, and reports fundamentals as unavailable context.
- `signaldesk ta <SYMBOL> --mode enhanced --llm none --output json` resolves enhanced roles through `signaldesk providers mode`. When `FMP_API_KEY` is configured and FMP is registered, FMP may provide price, fundamentals, and catalyst roles.
- If the FMP key is missing or an enhanced provider cannot supply a role, SignalDesk falls back to the default price path and emits explicit unavailable-context entries instead of treating missing data as `no catalyst` or `no risk`.
- Explicit `--provider <name>` remains a targeted price-provider override for smoke checks and local fixtures; role-mode resolution is the path that unlocks enhanced fundamentals and catalysts.

## Data boundaries

Enhanced context is rendered alongside, not inside, deterministic TA facts:

- `facts.fundamentals` contains provider-sourced company facts such as company name, sector, industry, market cap, valuation metrics, and the provider/source URL when available.
- `facts.catalysts` contains provider-sourced catalyst events such as headline, source, URL, summary, and publication timestamp. For FMP, this includes stock-news rows and earnings-calendar rows when the provider returns them.
- `provenance` records enhanced-context source, provider, generated timestamp, and warnings.
- `unavailable_context` records missing credentials, unsupported roles, empty provider payloads, disabled LLM narrative, or other absent context.
- `risks` and `scores` may reference unavailable fundamentals/catalysts as scope limits, but they must not invent facts or silently infer that no catalyst exists.

## Freshness and attribution

Every enhanced payload must carry provider attribution and timestamps. If a fundamental or catalyst timestamp is absent or older than the deterministic freshness threshold, currently 7 days for enhanced context, report warnings in provenance. Stale warnings are context about data quality; they are not trading recommendations.


## Redistribution boundary

Enhanced provider payloads can be used to produce canonical facts, risks, unavailable context, and provenance for the runtime operator, but paid or license-restricted raw payloads must not be committed or published as fixtures, report examples, screenshots, dumps, or dashboard artifacts unless redistribution is explicitly permitted. Prefer synthetic/open fixtures for tests and docs. If enhanced context cannot be fetched or shared safely, keep it as explicit unavailable context rather than implying the catalyst/fundamental risk is absent. See [Provider data redistribution policy](provider-data-redistribution.md).

## Runtime verification examples

Default-mode smoke checks must work without paid keys:

```bash
signaldesk ta AMD --provider local-fixture --llm none --output json
signaldesk providers mode --mode enhanced --output json
```

With `FMP_API_KEY` configured, enhanced-mode checks should show FMP roles and enriched `facts`/`provenance` fields. Without the key, they should show unavailable FMP fundamentals/catalysts while preserving the default price path.
