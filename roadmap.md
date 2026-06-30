# SignalDesk Roadmap Index

GitHub issues are now the canonical execution plan for SignalDesk. This file is only an index and policy reference; agents should not translate this file into issues or use it as a private backlog.

## Canonical rule

Read and operate from GitHub issues:

```bash
gh issue list --repo Sukhraj1000/signaldesk --state open --label roadmap
gh issue view <number> --repo Sukhraj1000/signaldesk
```

The old roadmap-to-issues step has been removed. If a capability is not represented in GitHub, create or update a GitHub issue directly with the required contract below.

## Roadmap issues

- #43 Roadmap 0: Product Contract and Non-Goals
- #44 Roadmap 1: Engineering Foundation and Quality System
- #45 Roadmap 2: Domain Model and Data Contracts
- #46 Roadmap 3: Provider Layer, Reliability, and Data Tiers
- #47 Roadmap 4: Technical Analysis Engine
- #48 Roadmap 5: Levels, Events, Risk, and Scoring
- #49 Roadmap 6: Signal Card Assembly
- #50 Roadmap 7: CLI Product Workflows
- #51 Roadmap 8: Watchlists and Scanning
- #52 Roadmap 9: Reporting and Data Presentation
- #53 Roadmap 10: Enhanced Catalyst and Fundamentals Layer
- #54 Roadmap 11: LLM Explanation Layer
- #55 Roadmap 12: API Layer
- #56 Roadmap 13: Dashboard and Visualization
- #57 Roadmap 14: Persistence, Caching, and Scheduling
- #58 Roadmap 15: Backtesting and Evaluation
- #59 Roadmap 16: Observability and Operations
- #60 Roadmap 17: Security, Compliance, and Safety
- #61 Roadmap 18: Developer and Agent Workflow
- #253 Roadmap 19: Decision-support Trading Signal Engine

## Issue contract

Every roadmap or implementation issue should include:

- user-facing outcome
- architecture layer touched
- provider mode impact: default, enhanced, both, LLM, or none
- acceptance criteria
- tests to add/update
- runtime or smoke verification
- data/provenance expectations
- out-of-scope notes

## Workflow rule

Heartbeat agents should read GitHub issues, PRs, comments, CI, and runtime evidence directly. They should choose the next bounded lane from that state.

The old planning/translation agent is replaced by a reviewer/aligner/integrator agent. That agent checks that code being added to the codebase still makes sense for the whole product and aligns with:

- `architecture.md`
- open roadmap issues labeled `roadmap`
- `AGENTS.md`
- `docs/reviewer-aligner-integrator-agent.md`
- runtime verification evidence

## Closing roadmap issues

A roadmap issue should close only when the relevant capability is delivered, documented, tested, and reviewed for architecture alignment. Child implementation issues may close earlier, but the parent roadmap issue should remain open until the whole capability is usable.
