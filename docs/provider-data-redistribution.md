# Provider data redistribution policy

SignalDesk can render provider-sourced market context for the user who ran the command, but it must not turn paid or license-restricted provider payloads into checked-in datasets, public fixtures, or redistributable report bundles. This policy applies to enhanced providers such as FMP and any future paid price, fundamentals, catalyst, news, or estimate adapter.

## Allowed by default

- Use provider responses transiently to build canonical SignalDesk facts, deterministic signals, risks, unavailable context, and provenance for the requesting runtime session.
- Store deterministic local fixtures that are synthetic or explicitly open/test data, such as `local-fixture` and generated `local-csv` demo files.
- Include compact provenance in reports: provider name, source category, timeframe, generated timestamp, inputs, observation counts, and safe warnings.
- Commit tests that use redacted/minimal fixtures created for contract validation rather than copied paid-provider payloads.

## Not allowed without explicit permission

- Commit raw or near-raw paid-provider responses, market-data dumps, news bodies, fundamentals tables, analyst estimates, or generated reports that expose licensed payloads.
- Publish enhanced-provider artifacts as public fixtures, examples, golden files, screenshots, or documentation snippets when the content comes from a paid or restricted provider.
- Treat `--save-dir` report JSON as a redistribution cache for provider data. Saved artifacts are local runtime outputs for the operator who generated them, not reusable public datasets.
- Hide missing enhanced context to avoid license limits. If data cannot be fetched or shared, render unavailable context with safe details instead.

## Implementation expectations

Provider adapters should normalize external payloads into canonical models, preserve attribution/provenance, and redact credentials or operational details before diagnostics reach logs, CLI output, reports, tests, or PR comments. Report and dashboard renderers should prefer compact derived fields plus provenance over raw provider payloads.

When a PR touches enhanced-provider payloads, fixtures, reports, or docs examples, its body should state whether any sample data came from a paid/restricted source. If yes, the PR must either prove redistribution is permitted or replace the sample with synthetic, open, or redacted data and keep unavailable context explicit.
