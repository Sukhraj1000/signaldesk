# Agent Heartbeat Loop

This is the intended SignalDesk workflow. The important part is the loop: every pass reads the current project state, chooses the next bounded lane, updates GitHub context, and then waits for feedback before continuing.

## Source of truth

Use these, in order:

1. roadmap: what we intend to build
2. GitHub issues: scoped units of work
3. PRs: proposed code changes
4. PR comments and review comments: feedback that should modify the branch
5. CI/check results: executable feedback
6. human approval: merge gate

Do not rely on an agent's private memory as the source of truth. Durable context should be in issues, PR bodies, comments, docs, and code.

## Heartbeat pass

A heartbeat is a poll of repo state. It does not need to code by itself.

```text
heartbeat
  -> read roadmap
  -> read open issues
  -> read open PRs
  -> read PR comments/review comments
  -> read CI status
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

### Feature lane

Triggered when an open feature issue has no active PR.

Output:
- branch from `main`
- implementation
- tests
- PR linked to the issue
- merge-readiness report pasted into PR

### Bug lane

Triggered when an open bug issue has no active PR or a PR has failing tests.

Output:
- failing regression test where practical
- minimal fix
- targeted tests plus full checks
- PR comment explaining the fix evidence

### Review-response lane

Triggered when a PR has unresolved comments or review comments.

Output:
- branch update that responds to the comments, or a written reason not to change
- tests rerun
- PR comment summarising what changed

### Cleanliness lane

Triggered when the repo has duplicated code, stale docs, weak tests, or CI/tooling drift.

Output:
- small refactor or chore PR
- no behavior change unless explicitly scoped
- checks remain green

### Human-review lane

Triggered when checks are green and the only remaining gate is approval.

Output:
- concise PR summary for the human
- no merge unless human approval is present

### Auto-merge lane

Triggered when all merge gates are satisfied.

Required before auto-merge:
- required CI/checks are green
- required human approval is present
- GitHub conversations/review comments are resolved or explicitly answered
- branch protection reports the PR as mergeable
- no hold/no-merge label or human stop instruction is present

Output:
- enable squash auto-merge
- delete the branch after merge
- heartbeat moves to the next issue/roadmap slice after GitHub merges it

This keeps the loop moving without asking for another manual step after feedback has already been addressed.

## CodeRabbit / external review tools

CodeRabbit can sit in the review stage, but it should not be the whole safety story.

Use it as:
- extra review comments on PRs
- style/maintainability suggestions
- possible bug spotting
- approval signal after its comments are resolved and pre-merge checks are green

Still require:
- project CI
- local or CI test evidence
- human approval for merge
- agent response to unresolved comments

If CodeRabbit comments on a PR, the next heartbeat should route that PR into the review-response lane.

The repository config enables CodeRabbit's `request_changes_workflow`, so the intended loop is:

```text
CodeRabbit requests changes or leaves comments
  -> review-response agent updates the branch or replies with rationale
  -> CI runs again
  -> CodeRabbit approves when comments are resolved and checks are green
  -> GitHub auto-merge merges the PR
```

For this workflow, branch protection should require a review but should not require CODEOWNER review only; otherwise CodeRabbit approval cannot satisfy the merge gate.

## Mini-checks inside the loop

Each sub-agent should run the smallest useful ladder:

0. include the full handoff contract from `AGENTS.md` in the PR description or summary
1. preflight: right repo, right branch, no obvious secrets
2. targeted test or reproduction
3. lint/typecheck/test as appropriate
4. merge-readiness report
5. PR review comments resolved or explicitly answered
6. CI green
7. human approval before merge
8. squash auto-merge once all comments are addressed and GitHub gates are satisfied

## Stop rules

Stop and ask/report instead of continuing when:

- a task needs production secrets
- a change touches risky paths and the intent is unclear
- tests fail for a reason unrelated to the task
- issue comments conflict with roadmap direction
- the branch has drifted too far from `main`
- a human has requested hold/no-merge

## Loop memory rule

Never forget the loop:

- GitHub context tells us what changed since the last heartbeat.
- Sub-agents do bounded work.
- PR comments and CI are feedback.
- The next heartbeat consumes that feedback.
- Approval and addressed comments are explicit gates; once those gates and CI are satisfied, auto-merge is allowed.
