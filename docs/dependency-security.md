# Dependency and security checks

SignalDesk currently has a small Python dependency surface, so the mandatory gate is intentionally proportional and deterministic.

## Mandatory offline gate

Run:

```bash
make dependency-scan PYTHON=.venv/bin/python
```

This executes `scripts/dependency_security_check.py`, an offline check over `pyproject.toml` that verifies declared dependencies:

- include a lower bound such as `>=` or `~=`;
- do not use direct URL/path dependencies in CI-scanned dependency metadata;
- do not use wildcard or empty exact pins;
- do not include a conservative denylist of abandoned or ambiguous package names.

The check does not read `.env` files, provider keys, or the installed environment. Its output is limited to package requirement strings from `pyproject.toml`, so it is safe to run in local development and CI without secrets.

## CI mapping

The full local gate includes the dependency/security check through `tox`:

```bash
make check PYTHON=.venv/bin/python
```

CI runs the same `dependency-scan` tox environment in the Python matrix, and the Agent safety job also runs `python scripts/dependency_security_check.py` directly. This keeps the required GitHub check names stable while adding an explicit dependency hygiene signal.

## Manual vulnerability audits

Live vulnerability database audits are deliberately not required yet because they can depend on network availability, external service behavior, or scanner-specific package state. When the dependency surface grows, run a manual audit from a clean environment and report findings in the relevant issue or PR.

A suitable future enhancement can add a pinned scanner such as `pip-audit` or another maintained tool if it remains deterministic enough for CI and does not require secrets.
