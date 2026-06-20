# SignalDesk Backend

The backend package contains SignalDesk's domain models, provider contracts, deterministic analysis logic, and future signal-card/report assembly services.

## Responsibility

The backend is the source of truth for market analysis. It should:

- normalize provider data into canonical models
- calculate indicators, levels, events, risks, and scores deterministically
- assemble signal-card data structures
- preserve provenance and unavailable context
- expose pure functions/services that CLI, API, dashboard, and reports can share

The backend should not:

- print CLI output
- render dashboard components
- call LLMs directly from the TA engine
- hide provider failures
- mix enhanced data into default facts without provenance

## Provider tiers

### Default tier

The default tier makes the project useful without paid keys.

- yfinance as the primary default price adapter
- local fixture and CSV adapters for deterministic tests and demos
- no LLM required

### Enhanced tier

Enhanced adapters add richer, more reliable, more polished context.

- FMP is the first enhanced target
- later Polygon, Twelve Data, news/fundamental providers, and crypto providers if needed
- enhanced data should populate catalyst/fundamental context separately from technical facts

## Deterministic analysis

The TA engine should accept canonical candles and return typed analysis. It should not perform network calls or depend on CLI/API/dashboard code.

Current and planned analysis areas:

- indicators: SMA/EMA, RSI, MACD, ATR, volume average, relative volume
- levels: swing highs/lows, support/resistance, Fibonacci, confirmation/invalidation
- events: breakout/breakdown, moving-average reclaim/loss, bounce/rejection, failed breakout
- risk: liquidity, stale data, overextension, fallback/provider risk, missing context
- scoring: setup quality, risk score, data quality score

## Output contracts

Backend user-facing structures should preserve:

- facts
- deterministic signals
- risks
- unavailable context
- provenance
- optional explanation fields supplied by a separate LLM layer
