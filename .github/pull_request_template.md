## Summary

-

## Type

- [ ] Feature
- [ ] Bug fix
- [ ] Review/refactor
- [ ] CI/safety/docs

## Verification

Paste real command output or CI links. Do not write "not run" without explaining why.

- [ ] `make agent-preflight`
- [ ] `make check`
- [ ] `make merge-readiness`

## Agent handoff contract

- [ ] Changed files are listed or summarized
- [ ] Commands run and exact results are included
- [ ] Remaining risks or skipped checks are stated
- [ ] Secrets/dependencies/CI/Docker/scripts/releases/risky paths touched are declared
- [ ] PR/review comments are addressed or explicitly answered, if this is a review-response pass

## Risk checklist

- [ ] No secrets, tokens, `.env`, or credentials committed
- [ ] No direct push to `main`
- [ ] Risky paths reviewed if touched: auth, env, dependencies, CI, Docker, scripts, releases
- [ ] Market facts/signals/opinions remain separated where applicable
- [ ] AI-generated changes were reviewed by a human before merge

## Merge-readiness report

Paste `make merge-readiness` output here.
