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
```

Individual checks are also available:

```bash
make lint
make typecheck
make test
make fix
make format
```

## Local Services

Postgres and Redis are included for later milestones:

```bash
docker compose up -d
docker compose down
```

## Environment

Copy `.env.example` to `.env` for local configuration. Keep `.env` out of git.
