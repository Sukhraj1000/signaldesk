# Local check parity with CI

SignalDesk keeps one local command as the developer-facing mirror of pull request CI:

```bash
make check PYTHON=.venv/bin/python
```

That command runs `python -m tox`, and `tox.ini` currently expands the default environment list in this order:

1. `lint` - Ruff checks the repository.
2. `typecheck` - mypy type-checks the package.
3. `py` - pytest runs the Python test suite.
4. `docs` - `scripts/docs_check.py` verifies Markdown local links and anchors.
5. `dependency-scan` - `scripts/dependency_security_check.py` verifies declared dependency hygiene without network or secrets.
6. `smoke` - installs the package and runs deterministic no-network CLI smoke commands.

## CI mapping

The required GitHub check contexts are job-level checks, not one check per tox environment:

| Required GitHub check | What it runs | Local equivalent |
| --- | --- | --- |
| `Python checks (3.12)` | `tox -e lint`, `tox -e typecheck`, `tox -e py`, `tox -e docs`, `tox -e dependency-scan`, `tox -e smoke` on Python 3.12 | `make check PYTHON=.venv/bin/python` from a Python 3.12 venv |
| `Python checks (3.13)` | `tox -e lint`, `tox -e typecheck`, `tox -e py`, `tox -e docs`, `tox -e dependency-scan`, `tox -e smoke` on Python 3.13 | `python3.13 -m tox` or a Python 3.13 venv |
| `Agent safety checks` | `python scripts/agent_preflight.py`, `python scripts/merge_readiness.py`, and `python scripts/dependency_security_check.py` on pull requests | `make agent-preflight PYTHON=.venv/bin/python`, `make merge-readiness PYTHON=.venv/bin/python`, and `make dependency-scan PYTHON=.venv/bin/python` |

The CI job names are intentionally stable because branch protection keys off those exact contexts.

## Recommended local ladder for agents

Run these from a disposable task branch or worktree, not directly on `main`:

```bash
make agent-preflight PYTHON=.venv/bin/python
make check PYTHON=.venv/bin/python
make merge-readiness PYTHON=.venv/bin/python
```

For changes that affect user-facing runtime behavior, also run the affected entrypoint. Examples:

```bash
signaldesk --help
signaldesk health
signaldesk providers list
signaldesk providers check
```

Live provider checks, such as `signaldesk ta AMD --provider yfinance --llm none --output json`, are useful local evidence when optional dependencies and network access are available. They are not mandatory deterministic CI gates because they can depend on external services.

## Common blockers

- `make agent-preflight` fails on `main`: create a task branch or disposable worktree first.
- `.venv/bin/python` is missing: create the virtual environment with the README setup steps, then install `.[dev]`.
- `tox` is missing from the selected interpreter: run `python -m pip install -e ".[dev]"` or install tox into the venv.
- Docs checks fail on an anchor: update the Markdown link to match GitHub-style heading anchors.
- Dependency/security checks fail: update `pyproject.toml` to use bounded, registry-based dependencies or document a reviewed exception in the relevant issue before changing the gate.
- Live provider checks fail due to missing optional dependencies or network/provider availability: report the unavailable context instead of making CI depend on the live provider.
