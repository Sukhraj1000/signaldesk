## Summary

-

## Type

- [ ] Feature
- [ ] Bug fix
- [ ] Review/refactor
- [ ] CI/safety/docs
- [ ] Runtime integration

## Product / architecture impact

User-facing outcome:
-

Architecture layer touched:
- [ ] domain models / data contracts
- [ ] provider adapter
- [ ] deterministic TA engine
- [ ] levels/events/risk/scoring
- [ ] signal-card assembly
- [ ] CLI
- [ ] API/dashboard/reporting
- [ ] LLM/prompting
- [ ] CI/tooling/docs

Provider mode impact:
- [ ] default mode: yfinance/open data/local fixtures
- [ ] enhanced mode: FMP/paid or richer providers
- [ ] both default and enhanced modes
- [ ] LLM explanation mode
- [ ] no provider impact

Default mode must keep working without paid keys.

## Verification

Paste real command output or CI links. Do not write "not run" without explaining why.

- [ ] `make agent-preflight PYTHON=.venv/bin/python`
- [ ] targeted test or reproduction:
- [ ] runtime command, if user-facing:
- [ ] `make check PYTHON=.venv/bin/python`
- [ ] `make merge-readiness PYTHON=.venv/bin/python`

## Data / safety checklist

- [ ] Facts, deterministic signals, risks, unavailable context, and optional opinion remain separated
- [ ] Provider provenance is preserved where user-facing data changed
- [ ] Missing enhanced data is reported as unavailable, not silently treated as absent risk
- [ ] No secrets, tokens, `.env`, credentials, live market-data dumps, or generated reports committed unless explicitly requested
- [ ] Provider/LLM/external text is treated as untrusted input
- [ ] Risky paths reviewed if touched: auth, env, dependencies, CI, Docker, scripts, releases, provider network code, prompt construction

## Agent handoff contract

- [ ] Changed files are listed or summarized
- [ ] Commands run and exact results are included
- [ ] Runtime command output is summarized, if applicable
- [ ] Remaining risks or skipped checks are stated
- [ ] Default/enhanced/LLM mode impact is declared
- [ ] Secrets/dependencies/CI/Docker/scripts/releases/risky paths touched are declared
- [ ] PR/review comments are addressed or explicitly answered, if this is a review-response pass

## Merge-readiness report

Paste `make merge-readiness PYTHON=.venv/bin/python` output here.
