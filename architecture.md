# SignalDesk Architecture

## Purpose

SignalDesk is an open-source, TA-first market intelligence workbench. It turns market data into deterministic, explainable signal cards and reports. It is not a live trading bot, broker integration, portfolio manager, or LLM-first stock picker.

## Product contract

SignalDesk must always be useful in default open-source mode. Enhanced adapters add depth, reliability, and richer context, but they must not be required for the core technical-analysis workflow.

The durable user-facing contract lives in `docs/product-contract.md`. Architecture changes should preserve that contract unless a future GitHub issue explicitly updates it.

Default workflow:

```bash
signaldesk ta AMD --provider yfinance --llm none --output json
```

Future richer workflow:

```bash
signaldesk ta AMD --price-provider fmp --fundamentals-provider fmp --catalyst-provider fmp --llm openrouter
```

## Core principles

1. Deterministic core first.
   Code calculates prices, indicators, levels, events, risk flags, and scores. LLMs explain structured facts only.

2. Ports and adapters.
   Providers, CLI, API, dashboard, report writers, and LLMs are adapters around a pure backend/domain core.

3. Contract-first data design.
   Raw provider payloads are normalized into canonical models before analysis. Reports and UI render canonical outputs rather than recomputing analysis.

4. Explicit provenance.
   Every analysis output should identify provider, timeframe, generated timestamp, data range, fallbacks, and unavailable context.

5. Default plus enhanced data tiers.
   yfinance/basic open data should power a useful default mode. FMP and similar adapters add richer facts, reliability, catalysts, and fundamentals.

6. Runtime-first quality.
   Every PR should prove the installed program still starts and core commands work, not only that isolated tests pass.

7. Safety by design.
   Missing data is shown as unavailable. Provider text/news/issue content is untrusted. Secrets are redacted. LLMs cannot invent facts.

## High-level system diagram

```text
                         ┌─────────────────────────────┐
                         │ CLI / API / Dashboard / Jobs │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │ Workflow Orchestration       │
                         │ ta / scan / report           │
                         └──────────────┬──────────────┘
                                        │
          ┌─────────────────────────────┼─────────────────────────────┐
          ▼                             ▼                             ▼
┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
│ Price Providers  │          │ Catalyst Providers│         │ Fundamentals     │
│ yfinance default │          │ FMP/news enhanced │         │ FMP enhanced     │
│ FMP/Polygon/etc. │          │ unavailable ok    │         │ unavailable ok   │
└────────┬─────────┘          └────────┬─────────┘          └────────┬─────────┘
         │                             │                             │
         ▼                             ▼                             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Canonical Data Layer                                                         │
│ Symbol / Candle / Quote / CatalystContext / FundamentalContext / Provenance  │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Deterministic Analysis Core                                                  │
│ indicators -> levels -> events -> risk -> scoring -> SignalCard              │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Presentation Layer                                                           │
│ JSON / table / Markdown / future API response / future dashboard cards       │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Optional LLM Explanation Layer                                               │
│ Receives structured SignalCard only; returns schema-validated narrative       │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Provider architecture

Provider roles should become explicit over time:

- Price provider: candles, quotes, volume.
- Catalyst provider: earnings, news, filings, material events.
- Fundamentals provider: company profile, financial metrics, analyst/estimate context.
- LLM provider: explanation only, never source-of-truth data.

Current CLI may expose a simple `--provider` flag. GitHub roadmap issues should evolve this toward role-specific provider config once enhanced data expands.

### Default adapter tier

Default tier must make SignalDesk immediately useful.

- Primary default: yfinance
- Local deterministic sources: fixture provider, CSV provider
- Stooq/no-key providers may be secondary only if runtime reliability is understood
- No paid credentials required
- Suitable for open-source users, local demos, single-symbol TA, and watchlist scans

### Enhanced adapter tier

Enhanced tier adds richer context and reliability when configured.

- First enhanced adapter: FMP
- Later: Polygon, Twelve Data, Alpha Vantage, selected news/fundamental providers
- Adds earnings, company facts, fundamentals, catalysts, analyst context, and potentially cleaner paid price feeds
- Must clearly expose missing credentials and unavailable data

## Data contracts

Canonical models should separate layers:

1. Raw provider response.
2. Canonical market/fundamental/catalyst entities.
3. Derived analysis entities.
4. Presentation/report artifacts.

Important models:

- `Symbol`
- `Candle`
- `Quote`
- `ProviderResult`
- `ProviderCapability`
- `Provenance`
- `TechnicalSnapshot`
- `KeyLevels` / future `LevelSet`
- `TechnicalEvent`
- future `RiskAssessment`
- future `SignalCard`
- future `ReportArtifact`

## Deterministic analysis core

The TA core accepts canonical candles and returns typed analysis. It must not fetch network data, read `.env`, call Typer/FastAPI, render dashboard components, or call LLMs.

Responsibilities:

- indicators: SMA/EMA, RSI, MACD, ATR, volume average, relative volume
- levels: swing highs/lows, support/resistance zones, Fibonacci, confirmation/invalidation
- events: moving-average reclaim/loss, breakout/breakdown, failed breakout, bounce/rejection, overextension
- risk: liquidity, stale data, insufficient history, overextension, provider fallback, missing catalyst context
- scoring: setup quality, data quality, risk score

## Signal card shape

Signal cards are the canonical user-facing analysis object.

A mature signal card should contain:

- identity: symbol, generated timestamp, timeframe
- provider mode: default/enhanced, price/catalyst/fundamental/LLM providers
- facts: latest close, volume, candle range, data freshness
- trend: moving-average and momentum context
- levels: support, resistance, confirmation, invalidation
- events: recent deterministic technical events
- risk: risk flags and missing context
- score: setup quality, risk, and data quality
- provenance: source adapters, fallback status, warnings
- optional explanation: schema-validated LLM narrative from structured facts only

## Presentation standards

Outputs must separate:

- Facts: prices, volumes, timestamps, provider data.
- Signals: deterministic interpretations such as breakout, reclaim, relative volume spike.
- Risks: reasons to reduce confidence or avoid chasing.
- Missing context: unavailable catalysts, fundamentals, stale data, provider failures.
- Opinion/narrative: optional explanation, never treated as fact.

Avoid raw indicator dumps as the primary UX. Reports should answer what matters, why, what confirms, what invalidates, and what data is missing.

## LLM guardrails

LLMs are optional and late-stage.

- `LLM_PROVIDER=none` is a first-class mode.
- LLM input is structured `SignalCard` JSON only.
- Provider/news text is untrusted content.
- LLM output must be schema-validated.
- LLMs cannot invent prices, levels, catalysts, earnings, or fundamentals.
- Invalid LLM output fails closed.

## Quality, CI, and runtime gates

Every PR should run:

- lint
- typecheck
- unit/integration tests
- installed CLI smoke
- agent preflight/merge readiness where applicable
- external review where configured

Deterministic CI should avoid live network and paid credentials. Live provider tests belong in manual/dev checks or explicitly designed scheduled checks.

## Non-goals

Do not build yet:

- broker execution
- live trading
- portfolio auto-rebalancing
- screenshot-based chart analysis
- complex real-time websocket infrastructure
- Kubernetes/microservices
- paid data redistribution
- LLM-generated market facts
