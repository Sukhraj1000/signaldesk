# AI Agent Development Loop

SignalDesk should be safe for AI-assisted development while staying simple enough to run locally. Agents are bounded contributors that improve a runtime-proven product, not autonomous maintainers.

## Product principles inside the loop

- Default mode must work with open data, with yfinance as the primary default price adapter.
- Enhanced adapters such as FMP add richer data and polish, but cannot be required for core workflows.
- Deterministic code calculates facts, indicators, levels, events, risk flags, and scores.
- LLMs explain structured facts only and remain optional.
- Reports must separate facts, signals, risks, unavailable context, and optional opinion.

## Loop overview

```text
GitHub issue or runtime/product gap
  -> classify: feature / bug / review / chore / docs / runtime-integration
  -> identify provider mode: default / enhanced / both / LLM
  -> risk triage
  -> branch or sandbox workspace
  -> context pack
  -> implementation agent
  -> local checks + runtime smoke
  -> reviewer/aligner/integrator pass
  -> human or bot review
  -> PR
  -> CI and safety gates
  -> human approval
  -> merge
  -> post-merge validation
```

## Roles

### Feature agent

Builds scoped functionality from an issue or task.

Rules:

- start from a fresh branch
- state the user-facing capability
- state whether default/enhanced provider modes are affected
- add or update tests for visible behavior
- avoid broad refactors unless the issue asks for them
- run `make check`
- run relevant CLI/runtime command when behavior is user-facing
- produce a merge-readiness report

### Runtime integration agent

Used when the product path is not proven.

Rules:

- run the installed CLI/API/app, not just unit tests
- reproduce the missing command, crash, bad output, or provider failure
- add smoke coverage where appropriate
- fix only the integration blocker unless explicitly scoped
- verify default mode still works without paid keys

### Bug agent

Fixes a reproduced failure.

Rules:

- write or identify the failing regression test first when practical
- prove the failure before the fix when reproducible locally
- keep the production patch minimal
- run targeted tests and then `make check`

### Reviewer / aligner / integrator agent

Replaces the old roadmap-to-issues translator. Reviews the diff, linked issue, runtime evidence, and architecture fit, not the author's intent.

Focus:

- correctness and missing tests
- linked GitHub issue alignment
- architecture fit against `architecture.md`
- runtime behavior, not only isolated functions
- default/enhanced provider separation
- secret leakage
- risky paths
- dependency or CI changes
- overbuilt or unclear code
- market-data provenance and fact/signal/opinion separation

### Approver

Approves only when:

- CI is green
- merge-readiness report has no unexplained blockers
- runtime smoke evidence exists for user-facing paths
- risky path changes have been reviewed
- PR scope matches the issue or task

### Merger

Merges after approval. Default policy is squash merge into `main`, then verify main CI.

## Local commands

```bash
make agent-preflight PYTHON=.venv/bin/python
make check PYTHON=.venv/bin/python
make merge-readiness PYTHON=.venv/bin/python
```

Useful runtime commands:

```bash
signaldesk --help
signaldesk health
signaldesk providers list
signaldesk providers check
signaldesk ta AMD --provider yfinance --llm none --output json
```

## Context pack checklist

Before asking an AI coding tool to work, fill out `docs/context-pack-template.md` or paste its sections into the issue/PR comment/agent prompt.

At minimum, give it:

- repo path and remote: `Sukhraj1000/signaldesk`
- task goal and user-facing outcome
- GitHub issue URL/number
- provider mode impact: default, enhanced, both, or LLM
- relevant files and docs
- constraints from `AGENTS.md`
- exact checks it must run
- exact runtime command it should prove, if applicable
- explicit instruction not to merge, deploy, or expose secrets

## Safety model

Branch isolation is useful, but it is not a sandbox. For risky work, prefer one of:

1. devcontainer: clean Linux container with repo-mounted source
2. disposable git worktree: isolated branch directory
3. GitHub Actions CI: independent verification outside the agent workspace

Secrets should be opt-in. The default sandbox must not receive market-data keys, LLM keys, brokerage keys, or production credentials.

## Merge gates

A PR is merge-ready only when all required gates pass:

- branch is not `main`
- working tree is clean except intended tracked changes before commit
- `make check` passes locally or in CI
- relevant runtime command passes locally or is explained if skipped
- CI passes on the PR
- risky paths are reviewed
- human approval is present

## If the agent gets stuck

Stop the loop and report:

- exact command or test that failed
- smallest reproduction
- suspected cause
- what was tried
- provider mode affected
- next recommended step
