# SignalDesk Roadmap

This roadmap is architecture-led. It defines product capabilities, system boundaries, acceptance criteria, and verification expectations. Issues and PRs should be derived from these milestones, but the project should not blindly create branches just because a bullet exists.

## Roadmap rules

Every implementation issue should include:

- user-facing outcome
- architecture layer touched
- provider mode impact: default, enhanced, or both
- acceptance criteria
- tests to add/update
- runtime or smoke verification
- out-of-scope notes

Every PR should prove the real program still works through CI and smoke checks.

## 0. Product Contract and Non-Goals

### Goal

Define SignalDesk as an open-source, TA-first market intelligence workbench that remains useful in default mode and can become richer through enhanced adapters.

### Architecture

SignalDesk is deterministic first. Provider adapters fetch data, the backend normalizes and analyzes it, and presentation adapters render signal cards. LLMs explain structured facts only.

### User-facing capabilities

- `signaldesk ta AMD --provider yfinance --llm none --output json`
- `signaldesk providers list`
- `signaldesk providers check`
- future `signaldesk scan --watchlist watchlists/default.yaml`
- future `signaldesk report --watchlist watchlists/default.yaml --format markdown`

### Non-goals

- live trading
- broker execution
- portfolio auto-rebalancing
- LLM-created market facts
- screenshot-only chart analysis
- complex real-time infrastructure before batch workflows work
- paid data redistribution

### Acceptance criteria

- README and architecture docs state default vs enhanced provider modes.
- Roadmap items map to user workflows and quality gates.
- Missing data is treated as unavailable context, not as proof of no risk.

## 1. Engineering Foundation and Quality System

### Goal

Make every future change safe, testable, runtime-verified, and easy to review.

### Current status

- Python package and monorepo structure exist.
- Ruff, mypy, pytest, tox, Makefile, GitHub Actions, and CLI smoke checks exist.
- Branch protection requires CI and review.
- Agent preflight and merge-readiness scripts exist.

### Remaining work

- Add markdown/docs checks if useful.
- Add schema/golden-output tests for CLI JSON once signal-card schema stabilizes.
- Add dependency and security scanning once dependencies grow.
- Keep `make check PYTHON=.venv/bin/python` as the local mirror of CI.

### Acceptance criteria

- Every PR runs lint, typecheck, pytest, and installed CLI smoke.
- Main push CI remains green after merge.
- Runtime smoke includes core no-network commands.
- Live provider checks are manual or scheduled, not required deterministic CI.

## 2. Domain Model and Data Contracts

### Goal

Establish canonical models for raw data, normalized data, derived analysis, and presentation artifacts.

### Current status

Implemented:

- `Symbol`
- `Candle`
- `Quote`
- `ProviderResult`
- `ProviderCapability`
- `Provenance`
- `KeyLevels`
- `TechnicalEvent`
- `TechnicalSnapshot`
- `SignalCard`

### Needed refinements

- Add or refine `LevelSet` for support/resistance, Fibonacci, confirmation, and invalidation.
- Add `RiskAssessment` with typed flags and severity.
- Add `DataQuality` / `UnavailableContext` model.
- Add `ProviderMode` or equivalent fields: default/enhanced, price provider, catalyst provider, fundamentals provider, LLM provider.
- Add stable JSON serialization and schema tests for user-facing outputs.

### Acceptance criteria

- Domain models validate invariants.
- JSON output is stable and schema-tested.
- Provenance and unavailable context survive into reports.
- Raw provider data does not leak directly into presentation.

## 3. Provider Layer, Reliability, and Data Tiers

### Goal

Make data access pluggable, explicit, safe, and useful in both default and enhanced modes.

### Provider role model

SignalDesk should move toward explicit provider roles:

- price provider: candles, quotes, volume
- catalyst provider: earnings, news, filings, events
- fundamentals provider: company profile, financial metrics, analyst/estimate context
- LLM provider: explanation only

### Default adapter tier

Purpose: make SignalDesk work out of the box for open-source users.

Primary default adapter:

- yfinance

Local deterministic adapters:

- local fixture provider
- local CSV provider

Default tier requirements:

- no paid keys
- useful historical candles
- clear optional dependency status
- safe health checks
- provider failures are typed and redacted
- enough data for single-symbol TA and watchlist scans

### Enhanced adapter tier

Purpose: add richer, more reliable, more polished data when configured.

First enhanced adapter:

- FMP

Later enhanced adapters:

- Polygon
- Twelve Data
- Alpha Vantage if useful
- selected news/fundamentals providers
- CCXT/CoinGecko if crypto becomes first-class

Enhanced tier requirements:

- missing keys report `not configured`, not crash
- configured keys unlock richer facts and catalysts
- enhanced data is separated from TA facts
- reports clearly show which data came from enhanced adapters

### Current status

Implemented:

- provider contract and registry
- provider health/list CLI
- yfinance adapter
- Stooq adapter
- local CSV provider
- FMP adapter placeholder/partial support
- Polygon/Twelve Data placeholders
- credential redaction
- rate-limit handling
- fallback handling

### Remaining work

- Make yfinance the documented default provider path.
- Add provider role config once enhanced data expands.
- Harden Stooq/no-key provider status based on runtime reliability.
- Expand FMP into first-class enhanced price/fundamental/catalyst provider.
- Add provider capability fields for intervals, credential state, and live-check suitability.

### Acceptance criteria

- `signaldesk ta AMD` can eventually default to yfinance.
- `signaldesk providers list` distinguishes default and enhanced capabilities.
- `signaldesk providers check` is safe and redacted.
- FMP enriches signal cards without being required for default TA.

## 4. Technical Analysis Engine

### Goal

Produce deterministic technical snapshots from canonical OHLCV candles.

### Architecture

The TA engine is pure backend/domain code. It does not fetch provider data, print CLI output, call LLMs, or know about dashboards/API routes.

### Current status

Implemented:

- SMA/EMA
- RSI
- MACD
- ATR
- volume moving average
- relative volume
- swing highs/lows
- support/resistance zone detection

### Remaining indicators and analysis helpers

- indicator metadata and warmup diagnostics
- data quality warnings for insufficient candles
- trend regime classification
- volatility regime classification
- volume regime classification

### Acceptance criteria

- calculations are deterministic
- no network calls inside TA code
- insufficient data creates warnings where user-facing output needs them
- tests cover normal, edge, insufficient, and flat/tie cases

## 5. Levels, Events, Risk, and Scoring

### Goal

Move from raw indicators to useful setup interpretation.

### Levels

Needed:

- Fibonacci retracements
- confirmation/invalidation levels
- level strength scoring
- support/resistance zone metadata: touches, recency, width, source swings

### Events

Needed:

- reclaimed/lost moving averages
- breakout/breakdown
- failed breakout
- bounce/rejection
- overextension
- relative volume spike
- volatility expansion/compression
- trend regime shift

Event fields:

- event type
- timestamp/index
- severity
- source rule
- source levels/indicators
- human-readable reason
- invalidation condition where relevant

### Risk engine

Needed:

- liquidity risk
- stale data risk
- provider fallback risk
- insufficient history risk
- overextension risk
- earnings/catalyst risk when enhanced data is available
- trend conflict risk
- high-volatility risk

### Scoring

Needed:

- setup quality score
- risk score
- data quality score
- reason list for each score

### Acceptance criteria

- every event/risk/score is traceable to deterministic rules
- missing catalyst/fundamental data produces unavailable context
- no generated opinion is treated as a fact

## 6. Signal Card Assembly

### Goal

Assemble provider data, deterministic TA, levels, events, risk, scoring, and provenance into one canonical user-facing object.

### Signal card sections

- identity: symbol, timeframe, generated timestamp
- provider mode: default/enhanced and role providers
- facts: latest close, volume, data range, candle count
- trend: moving averages and momentum state
- levels: support, resistance, Fibonacci, confirmation, invalidation
- events: recent technical events
- risk: flags and missing context
- score: setup quality, risk, data quality
- provenance: providers, fallback status, warnings
- optional explanation: LLM narrative from structured facts only

### Acceptance criteria

- `signaldesk ta ... --output json` returns signal-card-shaped output.
- JSON schema/golden tests protect output contracts.
- CLI/API/dashboard/reporting all render from the same object.

## 7. CLI Product Workflows

### Goal

Make SignalDesk useful from the terminal before building API/dashboard layers.

### Current commands

- `signaldesk health`
- `signaldesk providers list`
- `signaldesk providers check`
- `signaldesk ta SYMBOL --provider yfinance --llm none --output json`

### Needed commands

- default provider behavior: `signaldesk ta AMD`
- `signaldesk scan --watchlist watchlists/default.yaml`
- `signaldesk report --watchlist watchlists/default.yaml --format markdown`
- `signaldesk config inspect`
- `signaldesk fixtures generate` or equivalent fixture tooling

### CLI standards

- JSON mode for machine-readable workflows
- errors to stderr
- no secrets in output
- provider/provenance visible
- unavailable context visible
- no silent fallback without warnings

### Acceptance criteria

- CI smoke covers no-network CLI commands.
- fixture-backed tests cover scan/report commands.
- live yfinance run works locally when optional extra is installed.

## 8. Watchlists and Scanning

### Goal

Move from single-symbol analysis to ranked watchlist intelligence.

### Watchlist model

- name
- symbols
- tags
- asset class
- provider preference
- enabled/disabled
- notes

### Scan pipeline

1. load watchlist
2. choose provider roles
3. fetch price data with bounded concurrency
4. assemble signal cards
5. rank setups
6. show failed/skipped symbols
7. output JSON/table/Markdown

### Ranking inputs

- trend alignment
- proximity to confirmation/breakout levels
- recent events
- relative volume
- risk flags
- data quality
- unavailable enhanced context

### Acceptance criteria

- one bad symbol does not fail the whole scan
- output includes ranked setups and failed/skipped symbols
- deterministic fixture watchlist test exists
- no paid keys required for default scan

## 9. Reporting and Data Presentation

### Goal

Turn signal cards into readable, decision-useful outputs.

### Formats

- JSON
- terminal table
- Markdown
- later PDF/DOCX-style export
- later dashboard cards

### Presentation standards

Reports must separate:

- facts
- deterministic signals
- risks
- unavailable context
- optional opinion/narrative

Reports should answer:

- what is the setup?
- why does it matter?
- what confirms it?
- what invalidates it?
- what risks or missing data reduce confidence?

### Acceptance criteria

- reports render from `SignalCard`
- Markdown includes timestamp and provenance
- missing enhanced context is explicit
- output is compact enough to use, not raw indicator dumping

## 10. Enhanced Catalyst and Fundamentals Layer

### Goal

Add context beyond price action without corrupting deterministic TA.

### First enhanced path

FMP should become the first polished enhanced adapter because it can support:

- company facts
- earnings context
- financial metrics
- analyst/fundamental context where available
- richer news/catalyst context if supported

### Design rules

- catalyst/fundamental facts are separate from TA signals
- source attribution required
- timestamps required
- stale-data warnings required
- no LLM-generated facts

### Acceptance criteria

- `CatalystContext` and/or `FundamentalContext` exists
- FMP key unlocks richer signal-card fields
- missing key reports unavailable context
- default yfinance workflow still works without FMP

## 11. LLM Explanation Layer

### Goal

Generate readable explanations from structured signal cards only.

### Provider modes

- default: `LLM_PROVIDER=none`
- enhanced: OpenRouter/OpenAI-compatible adapter
- later: local/Ollama adapter

### Guardrails

- LLM receives structured JSON only
- LLM cannot fetch market data
- LLM cannot invent prices, levels, catalysts, or fundamentals
- provider/news text is untrusted input
- output schema is validated
- invalid output fails closed

### Acceptance criteria

- no-LLM output remains complete and useful
- prompt input shape is tested
- output parser/schema is tested
- malicious provider/news text cannot override instructions

## 12. API Layer

### Goal

Expose the same core workflows to web/dashboard clients.

### Endpoints

- `/health`
- `/providers`
- `/symbols/{symbol}/ta`
- `/scan`
- `/reports`
- later `/artifacts/{id}`

### Standards

- API returns same canonical schema as CLI JSON
- validation errors are typed
- fixture provider is used in CI tests
- no API-only analysis logic

### Acceptance criteria

- API smoke test starts server and hits `/health`
- API docs generated through OpenAPI
- CLI and API output contracts stay aligned

## 13. Dashboard and Visualization

### Goal

Present signal cards clearly without becoming a cluttered trading terminal.

### Views

- provider status
- symbol analysis
- watchlist scan
- signal card
- chart overlays
- report archive

### Visualization principles

- show confirmation/invalidation prominently
- label support/resistance and Fibonacci levels clearly
- highlight risk and unavailable context
- avoid implying false precision
- dashboard consumes canonical JSON

### Acceptance criteria

- fixture signal card renders end-to-end
- no dashboard-only analysis logic
- visual tests or screenshots exist once UI is active

## 14. Persistence, Caching, and Scheduling

### Goal

Make repeated scans efficient and reports recoverable without overbuilding early.

### Sequence

1. filesystem report artifacts
2. provider-response cache by provider/symbol/interval/date range
3. SQLite/Postgres only when workflows require persistence
4. Redis/job queue only when scheduling/concurrency requires it

### Scheduling

- local/manual first
- cron examples after report command is stable
- scheduled jobs should surface failures clearly
- no autonomous PR/cron loop unless product runtime gates remain green

### Acceptance criteria

- reports can be saved and read back
- cache invalidation is documented
- scheduled reports show provider failures/unavailable context

## 15. Backtesting and Evaluation

### Goal

Evaluate deterministic setup rules before adding more complexity.

### Scope

- rule replay over historical data
- no broker/execution assumptions
- fixture universe first
- walk-forward style validation
- setup usefulness metrics

### Metrics

- hit rate
- average forward return by horizon
- false breakout rate
- max adverse excursion proxy
- event usefulness
- data availability rate

### Acceptance criteria

- each setup label can be evaluated historically
- backtest reports include limitations
- no live trading behavior is introduced

## 16. Observability and Operations

### Goal

Make runtime failures diagnosable.

### Needed

- structured logs
- safe provider diagnostics
- scan/report run IDs
- provider timing summaries
- data freshness checks
- clear error taxonomy
- optional OpenTelemetry later

### Acceptance criteria

- CLI/API errors are actionable
- logs never expose secrets
- failed/skipped symbols are visible in scans and reports

## 17. Security, Compliance, and Safety

### Goal

Keep provider, LLM, and report workflows safe.

### Standards

- no secrets in git
- redact credentials in provider diagnostics
- dependency scanning as dependencies grow
- prompt-injection-aware LLM design
- untrusted external content cannot override system rules
- not-financial-advice disclaimer in public/report contexts
- paid data redistribution limitations documented

### Acceptance criteria

- preflight catches obvious secret mistakes
- LLM tests include malicious content
- reports include provenance and disclaimers where relevant

## 18. Developer and Agent Workflow

### Goal

Use AI agents as bounded contributors without turning the project into a blind issue factory.

### Rules

- no new PR without runtime goal and acceptance criteria
- issues describe product capabilities and architecture impact
- PRs include verification output
- review comments and CI failures feed the next action
- human approval remains the merge gate
- after merge, main CI must pass

### Acceptance criteria

- context packs include provider mode and runtime verification
- merge-readiness report accompanies PRs
- agent loop pauses for runtime-first integration when the product path is not proven
