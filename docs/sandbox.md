# Development Sandbox

Use the sandbox when an AI agent is doing more than a tiny docs change. The sandbox should protect the repo, secrets, and provider credentials while still proving the product works through real entrypoints.

## Option A: Devcontainer

Open the repo in a devcontainer-compatible editor or CLI. The container installs only Python, git, make, and project dev dependencies. By default, no secrets are added to the environment.

Expected setup command inside the container:

```bash
make check
```

## Option B: Disposable git worktree

From the repo root:

```bash
git fetch origin
mkdir -p ../signaldesk-worktrees
git worktree add ../signaldesk-worktrees/<task-name> -b feature/<task-name> origin/main
cd ../signaldesk-worktrees/<task-name>
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
make agent-preflight
```

Remove a clean worktree after merge:

```bash
git worktree remove ../signaldesk-worktrees/<task-name>
git worktree prune
```

## Default-mode sandbox

Default mode should need no paid credentials.

Allowed:

- local fixtures
- local CSV files designed for tests
- yfinance optional dependency for manual live checks
- no-LLM mode

Useful commands:

```bash
make check PYTHON=.venv/bin/python
signaldesk --help
signaldesk providers check
signaldesk ta AMD --provider yfinance --llm none --output json
```

Do not commit live market-data dumps unless explicitly requested and sanitized.

## Enhanced-mode sandbox

Enhanced adapters such as FMP may require keys. Use enhanced mode only when the task explicitly needs it.

Rules:

- use the smallest scoped test key available
- never paste keys into issues, PRs, logs, fixtures, or reports
- document which enhanced provider was used
- keep default mode working without the key
- prefer mocked/fixture tests in CI

## Secrets policy

Default sandbox runs must not receive:

- FMP, Polygon, Twelve Data, Alpha Vantage, broker, or exchange keys
- LLM provider keys
- GitHub tokens beyond normal checkout permissions
- production `.env` files

If a task needs a key, use the smallest scoped test key and document why in the PR. Provider diagnostics must redact keys and tokens.

## Runtime evidence policy

For user-facing changes, record the actual command and output summary in the PR. A passing unit test alone is not enough when the installed CLI/API/app path changed.
