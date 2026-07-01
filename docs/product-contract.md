# Product Contract

SignalDesk is an open-source, TA-first market intelligence workbench. It must remain useful with open data in default mode, while allowing optional enhanced adapters to add richer context when users configure them.

## Source of truth

Deterministic SignalDesk code is the source of truth for market facts, indicators, levels, events, risks, and scores.

| Layer | Responsibility | Must not do |
| --- | --- | --- |
| Providers | Fetch raw candles, quotes, fundamentals, catalysts, and provider status. | Invent missing market data or silently hide provider failures. |
| Backend/domain | Normalize provider data and calculate deterministic indicators, levels, events, risks, scores, and canonical signal-card objects. | Fetch network data from TA code, render CLI/dashboard output, or call LLMs. |
| CLI/API/dashboard/reports | Render canonical backend objects and preserve provenance/unavailable context. | Recompute analysis or blur facts, signals, risks, and narrative. |
| Optional LLM layer | Explain structured SignalDesk facts when enabled. | Create prices, levels, catalysts, fundamentals, recommendations, or risk claims. |

## Provider modes

### Default mode

Default mode is the baseline open-source workflow. It must work without paid credentials or an LLM.

- Primary live price adapter: `yfinance`.
- Deterministic local sources: fixtures and CSV files.
- Current user-facing scope: health checks, provider listing/checks, and single-symbol TA JSON/table output.
- Expected future scope: fixture-backed watchlist scans and reports.

Supported example:

```bash
signaldesk ta AMD --provider yfinance --llm none --output json
```

### Enhanced mode

Enhanced mode is optional. Adapters such as FMP can add richer or more reliable context, but they must not be required for core TA workflows.

- Enhanced data may include company facts, fundamentals, earnings, catalysts, analyst/estimate context, and paid price feeds.
- Enhanced fields must remain separated from deterministic TA facts.
- Missing keys or unavailable enhanced data must be reported as unavailable context, not treated as proof that no catalyst or risk exists.
- Paid provider payloads must not be redistributed through committed fixtures, public examples, generated reports, or dashboard artifacts unless explicitly permitted by the provider terms. See [Provider data redistribution policy](provider-data-redistribution.md).

## Output boundaries

User-facing contracts should keep these categories distinct:

- **Facts:** prices, volumes, timestamps, provider names, data ranges, candle counts.
- **Deterministic signals:** indicators, levels, events, risk flags, scores, and rule-derived reasons.
- **Risks:** traceable reasons to reduce confidence, including stale data, insufficient history, provider fallback, liquidity, volatility, or missing catalyst context.
- **Unavailable context:** provider failures, missing credentials, unsupported fields, absent catalyst/fundamental data, or disabled optional modes.
- **Optional narrative:** LLM or human-readable explanations of the structured facts above.

Unavailable context is not a negative fact. For example, missing catalyst data means `catalyst context unavailable`, not `no catalyst risk`.

### Unavailable-context contract

When a provider, optional mode, or data category cannot supply context, SignalDesk should carry an explicit unavailable-context entry instead of dropping the field or converting it into a reassuring statement.

Each unavailable-context entry should identify:

- **context type:** the missing category, such as `catalyst`, `fundamentals`, `earnings`, `provider_status`, or `llm_explanation`.
- **reason:** the deterministic reason SignalDesk knows, such as `provider not configured`, `optional dependency unavailable`, `unsupported interval`, `provider returned no data`, or `live check skipped`.
- **provider, when relevant:** the adapter associated with the unavailable context, for example `fmp`, `yfinance`, or `openrouter`.
- **details, when safe:** redacted operational detail that helps users understand the limitation without exposing secrets or paid payloads.

Consumers must not infer `no risk`, `no catalyst`, `no earnings event`, or `no fundamental concern` from unavailable context. They may only say that SignalDesk could not evaluate that category with the configured providers.

## Non-goals

SignalDesk must not imply or implement these capabilities unless a future issue explicitly changes the product contract:

- live trading
- broker execution
- portfolio auto-rebalancing
- LLM-created market facts, levels, catalysts, risks, or recommendations
- screenshot-only chart analysis
- complex realtime infrastructure before batch CLI workflows are proven
- paid data redistribution

## Agent and PR expectations

Every issue/PR should state provider-mode impact: default, enhanced, both, LLM explanation mode, or none. Runtime evidence should use supported entrypoints when examples change, and future commands must be clearly marked as future rather than presented as already available.
