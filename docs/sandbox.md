# Development Sandbox

Use the sandbox when an AI agent is doing more than a tiny docs change.

## Option A: Devcontainer

Open the repo in a devcontainer-compatible editor or CLI. The container installs only Python, git, make, and project dev dependencies. By default, no secrets are added to the environment. Secret exclusion is passive: developers must not inject secrets, and the sandbox does not actively filter manually added environment variables or files.

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

## Secrets policy

Default sandbox runs must not receive:

- FMP, Polygon, Twelve Data, Alpha Vantage, broker, or exchange keys
- LLM provider keys
- GitHub tokens beyond normal checkout permissions
- production `.env` files

If a task needs a key, use the smallest scoped test key and document why in the PR.
