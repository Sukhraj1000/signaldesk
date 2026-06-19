# AI Agent Development Loop

SignalDesk should be safe for AI-assisted development while staying simple enough to use locally.

## Loop overview

```text
issue or task
  -> classify: feature / bug / review / chore
  -> risk triage
  -> branch or sandbox workspace
  -> context pack
  -> implementation agent
  -> local checks
  -> review agent or human review
  -> PR
  -> CI and safety gates
  -> human approval
  -> merge
  -> post-merge validation
```

## Roles

### Feature agent

Builds scoped functionality from an issue.

Rules:
- start from a fresh branch
- add or update tests for visible behavior
- avoid broad refactors unless the issue asks for them
- run `make check`
- produce a merge-readiness report

### Bug agent

Fixes a reproduced failure.

Rules:
- write or identify the failing regression test first when practical
- prove the failure before the fix when the bug is reproducible locally
- keep the production patch minimal
- run targeted tests and then `make check`

### Review agent

Reviews the diff, not the author's intent.

Focus:
- correctness and missing tests
- secret leakage
- risky paths
- dependency or CI changes
- overbuilt or unclear code
- market-data provenance and fact/signal/opinion separation

### Approver

Approves only when:
- CI is green
- merge-readiness report has no unexplained blockers
- risky path changes have been reviewed by a human
- PR scope matches the issue

### Merger

Merges after approval. Default policy is squash merge into `main`.

## Local commands

```bash
make agent-preflight
make check
make merge-readiness
```

## Context pack checklist

Before asking an AI coding tool to work, fill out `docs/context-pack-template.md` or paste its sections into the issue/PR comment/agent prompt. The context pack must require explicit upstream confirmation of the handoff contract before dispatch: changed files, commands/results, remaining risks, and whether secrets/dependencies/CI/risky paths are touched.

At minimum, give it:

- repo path and remote: `Sukhraj1000/signaldesk`
- issue or task goal
- relevant files and docs
- constraints from `AGENTS.md`
- exact checks it must run
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
- CI passes on the PR
- risky paths are reviewed
- human approval is present

## If the agent gets stuck

Stop the loop and report:

- the exact command or test that failed
- the smallest reproduction
- suspected cause
- what was tried
- next recommended step
