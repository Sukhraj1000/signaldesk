# SignalDesk

SignalDesk is an open-source, TA-first market intelligence sandbox. It is intended to fetch market data, run deterministic technical analysis, and produce explainable signal cards. It is not a live trading bot.

## Repository Layout

```text
.
├── apps/
│   └── web/                 # Future web app
├── packages/
│   ├── backend/             # Python backend/domain package
│   └── cli/                 # Python CLI package
├── tests/                   # Shared test suite
├── architecture.md
├── docker-compose.yml
├── pyproject.toml
└── roadmap.md
```

## Local Setup

Use Python 3.12 or newer.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the checks:

```bash
make check
signaldesk --help
signaldesk health
signaldesk providers list
signaldesk providers check
```

Individual checks are also available:

```bash
make lint
make typecheck
make test
make smoke
make fix
make format
```

Run a live no-LLM technical-analysis pass when an external provider is available:

```bash
python -m pip install -e ".[dev,yfinance]"
signaldesk ta AMD --provider yfinance --llm none --output json
```

## Local Services

Postgres and Redis are included for later milestones:

```bash
docker compose up -d
docker compose down
```

## Environment

Copy `.env.example` to `.env` for local configuration. Keep `.env` out of git.
