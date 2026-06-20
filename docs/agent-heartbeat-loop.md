# Agent Heartbeat Loop

This is the intended SignalDesk workflow. The heartbeat reads current project state, chooses the next bounded lane, updates GitHub context, and waits for feedback before continuing.

The heartbeat must not become a blind issue factory. It should prefer runtime/product gaps, CI/review feedback, and roadmap dependencies that improve the real program.

## Source of truth

Use these, in order:

1. product contract and architecture docs
2. roadmap: what we intend to build
3. runtime evidence: what actually works/fails locally or in CI
4. GitHub issues: scoped units of work
5. PRs: proposed code changes
6. PR comments and review comments: feedback that should modify the branch
7. CI/check results: executable feedback
8. human approval: merge gate

Do not rely on an agent's private memory as the source of truth. Durable context should be in docs, issues, PR bodies, comments, code, and CI output.

## Heartbeat pass

```text
heartbeat
  -> read architecture and roadmap
  -> read current CI/main status
  -> read open issues and PRs
  -> read PR comments/review comments
  -> check runtime/smoke gaps
  -> choose lane
  -> dispatch one bounded sub-agent or report waiting state
  -> sub-agent updates branch/PR/comment
  -> checks and reviews create new feedback
  -> heartbeat repeats
```

Run locally:

```bash
make heartbeat
```

## Lanes

### Runtime-first integration lane

Triggered when the product path is not proven or user asks to pause blind PR creation.

Output:

- installed CLI/API/app command is run
- failure is reproduced or success is recorded
- smoke coverage is added if missing
- integration blocker is fixed
- default mode is verified without paid keys

Examples:

```bash
signaldesk --help
signaldesk providers check
signaldesk ta AMD --provider yfinance --llm none --output json
```

### Feature lane

Triggered when a roadmap capability has a clear user-facing outcome and no active PR.

Output:

- branch from `main`
- implementation
- tests
- runtime verification where applicable
- PR linked to the issue or task
- merge-readiness report pasted into PR

### Bug lane

Triggered when an open bug issue has no active PR or a PR has failing tests.

Output:

- failing regression test where practical
- minimal fix
- targeted tests plus full checks
- PR comment explaining the evidence

### Review-response lane

Triggered when a PR has unresolved comments or review comments.

Output:

- branch update that responds to the comments, or a written reason not to change
- tests rerun
- PR comment summarising what changed

### Cleanliness lane

Triggered when the repo has duplicated code, stale docs, weak tests, CI/tooling drift, or architecture docs that no longer match product direction.

Output:

- small refactor or docs/chore PR
- no behavior change unless explicitly scoped
- checks remain green

### Human-review lane

Triggered when checks are green and the only remaining gate is approval.

Output:

- concise PR summary for the human
- no merge unless human approval is present or the user has explicitly delegated merge after approval and all gates pass

### Auto-merge lane

Triggered only when all merge gates are satisfied and user/project policy permits it.

Required before merge:

- required CI/checks are green
- required approval is present
- GitHub conversations/review comments are resolved or explicitly answered
- branch protection reports the PR as mergeable
- no hold/no-merge label or human stop instruction is present

Output:

- squash merge
- delete branch after merge
- verify main CI after GitHub merges it

## Provider-mode awareness

Every heartbeat decision should identify whether the task affects:

- default mode: yfinance/open data/local fixtures
- enhanced mode: FMP/paid or richer adapters
- both modes
- LLM explanation mode

Default mode must remain useful even when enhanced adapters are unconfigured.

## CodeRabbit / external review tools

CodeRabbit can sit in the review stage, but it should not replace project CI, runtime checks, or human judgment.

Use it as:

- extra review comments on PRs
- style/maintainability suggestions
- possible bug spotting
- approval signal after comments are resolved and checks are green

If CodeRabbit comments on a PR, the next heartbeat should route that PR into the review-response lane.

## Mini-checks inside the loop

Each sub-agent should run the smallest useful ladder:

0. include the handoff contract from `AGENTS.md`
1. preflight: right repo, right branch, no obvious secrets
2. targeted test or reproduction
3. runtime command if user-facing behavior changed
4. lint/typecheck/test as appropriate
5. merge-readiness report
6. PR review comments resolved or explicitly answered
7. CI green
8. approval before merge
9. post-merge main CI verified

## Stop rules

Stop and ask/report instead of continuing when:

- a task needs production secrets
- a change touches risky paths and the intent is unclear
- tests fail for a reason unrelated to the task
- issue comments conflict with architecture/product direction
- the branch has drifted too far from `main`
- a human has requested hold/no-merge
- the requested task would make enhanced data required for default mode

## Loop memory rule

Never forget the loop:

- GitHub context tells us what changed since the last heartbeat.
- Runtime checks tell us whether the product actually works.
- Sub-agents do bounded work.
- PR comments and CI are feedback.
- The next heartbeat consumes that feedback.
