# SignalDesk

SignalDesk is an open-source, TA-first market intelligence workbench. It fetches market data, normalizes it into canonical domain models, runs deterministic technical analysis, and produces explainable signal cards and reports. It is not a live trading bot and it is not an LLM-first stock picker.

The core product principle is:

> Default mode must be useful with open data. Enhanced adapters add richer, more reliable context without becoming required for the core workflow.

## What SignalDesk does

SignalDesk answers practical market-analysis questions from a watchlist or ticker:

- What is the current technical setup?
- What levels matter?
- What would confirm or invalidate the setup?
- What risks or missing data should reduce confidence?
- Which provider produced the data and how fresh is it?

The deterministic backend calculates facts, indicators, levels, events, risk flags, and scores. LLMs, when enabled later, only explain structured facts and must never invent prices, levels, catalysts, or recommendations.

## Provider modes

### Default usable mode

The default mode should work for open-source users with minimal setup.

- Default price adapter: `yfinance`
- Also useful locally: fixtures and CSV files
- Purpose: historical candles, basic TA, watchlist scans, local demos, JSON/table/Markdown outputs
- No paid credentials required

Example:

```bash
signaldesk ta AMD --provider yfinance --llm none --output json
```

### Enhanced mode

Enhanced adapters add richer and more polished data when users bring keys.

- First enhanced adapter: FMP
- Later: Polygon, Twelve Data, Alpha Vantage, selected news/fundamental providers
- Purpose: richer company facts, earnings, fundamentals, catalysts, analyst context, more reliable paid data

Enhanced context must remain separate from technical facts. Missing enhanced data is reported as unavailable, not silently ignored.

## Architecture style

SignalDesk follows a ports-and-adapters shape:

```text
providers -> canonical data -> deterministic analysis -> signal cards -> CLI/API/reports/dashboard
```

Rules:

- Provider adapters fetch data but do not calculate trading logic.
- The TA engine is pure domain code with no network, CLI, API, dashboard, or LLM dependency.
- CLI/API/dashboard/reporting render the same canonical signal-card output.
- LLMs consume structured facts only and are optional.

See `docs/product-contract.md` for the durable product contract: supported default and enhanced provider modes, output category boundaries, unavailable-context handling, and non-goals.

## Non-goals

SignalDesk must not imply or implement these capabilities unless a future GitHub issue explicitly changes the product contract:

- live trading
- broker execution
- portfolio auto-rebalancing
- LLM-created market facts, levels, catalysts, risks, or recommendations
- screenshot-only chart analysis
- complex realtime infrastructure before batch CLI workflows are proven
- paid data redistribution

## Repository Layout

```text
.
├── apps/
│   └── web/                 # Future web dashboard, fed by canonical API output
├── docs/                    # Agent workflow, context packs, sandbox guidance
├── packages/
│   ├── backend/             # Domain models, providers, TA, risk, signal-card assembly
│   └── cli/                 # `signaldesk` command-line interface
├── tests/                   # Unit, integration, and CLI smoke tests
├── AGENTS.md                # AI-agent operating rules
├── architecture.md          # System architecture and design principles
├── docker-compose.yml       # Local services for later persistence/job milestones
├── pyproject.toml           # Python package metadata and tool config
└── roadmap.md               # Architecture-led delivery plan
```


## Planning model

GitHub issues are the canonical execution plan. `roadmap.md` is an index of roadmap issues, not a separate backlog to translate. Agents should read open issues, PRs, review comments, CI, and runtime evidence directly.

The old roadmap-to-issues agent role is replaced by a reviewer/aligner/integrator agent documented in `docs/reviewer-aligner-integrator-agent.md`.

## Local Setup

Use Python 3.12 or newer.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

For the default live adapter:

```bash
python -m pip install -e ".[dev,yfinance]"
```

## Checks

Run the full local gate:

```bash
make check PYTHON=.venv/bin/python
```

This mirrors CI and runs lint, typecheck, tests, Markdown docs link checks, and installed CLI smoke checks.

Individual checks:

```bash
make lint PYTHON=.venv/bin/python
make typecheck PYTHON=.venv/bin/python
make test PYTHON=.venv/bin/python
make docs PYTHON=.venv/bin/python
make smoke PYTHON=.venv/bin/python
make fix PYTHON=.venv/bin/python
make format PYTHON=.venv/bin/python
```

Core runtime smoke commands:

```bash
signaldesk --help
signaldesk health
signaldesk providers list
signaldesk providers check
```

Live default-mode TA check:

```bash
signaldesk ta AMD --provider yfinance --llm none --output json
```

## Quality gates

Every PR should prove:

- lint passes
- typecheck passes
- unit/integration tests pass
- installed CLI smoke passes
- risky paths are called out
- provider/LLM/secrets behavior is safe
- runtime bridges are tested, not only isolated functions

Live network/provider checks are useful for dev confidence, but deterministic CI should not depend on external network or paid credentials unless explicitly designed.

## Local Services

Postgres and Redis are included for later persistence/job milestones, not required for current CLI-first workflows.

```bash
docker compose up -d
docker compose down
```

## Environment

Copy `.env.example` to `.env` for local configuration. Keep `.env` out of git.

```text
APP_ENV=local
LLM_PROVIDER=none
FMP_API_KEY=
POLYGON_API_KEY=
```

Secrets must never appear in logs, PRs, generated reports, fixtures, or committed data.
