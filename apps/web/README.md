# SignalDesk Web

Placeholder for the future web application.

The web app should be a presentation adapter over canonical SignalDesk API/JSON output. It must not become a second implementation of technical analysis.

## Future purpose

The dashboard should help users inspect:

- provider status (current smoke: `signaldesk web provider-status --mode default --output json`)
- single-symbol signal cards
- watchlist scan results (current smoke: `signaldesk web watchlist-scan --watchlist watchlists/default.yaml --provider local-fixture --llm none --output json`)
- chart overlays for backend-emitted levels, events, confirmation, and invalidation (current smoke: `signaldesk web chart-overlays AMD --provider local-fixture --llm none --output json`)
- risk flags and unavailable context
- report history once persistence exists

## Design principles

- Feed UI components from canonical `SignalCard`/API output.
- Keep facts, signals, risks, unavailable context, and optional narrative visually distinct.
- Make provider mode visible: default yfinance/basic mode vs enhanced FMP/richer mode.
- Do not hide missing catalysts or fundamentals.
- Avoid chart clutter and false precision.
- No dashboard-only analysis logic.



## Current fixture rendering contract

The first dashboard slice is a renderer-facing presentation model for fixture signal cards:

- call extract_ta_signal_card(report) to select the nested canonical card
- call build_signal_card_presentation(signal_card) to group labels for UI sections
- render headline, provider_badge, level_groups, event_rows, risk_panel, score_rows, and provenance_rows

This keeps the future web app as a presentation adapter. It must not re-run indicators, infer support/resistance, hide unavailable context, or choose conflicting top-level aliases from the TA report.

## Future acceptance criteria

- dashboard renders fixture signal cards
- `/health` or equivalent app smoke is tested
- chart overlays are derived from backend level/event models
- visual tests or screenshots are added once UI becomes active


## Runtime smoke path

Until a browser dashboard exists, the fixture rendering contract is exercised through the CLI adapter:

```bash
signaldesk web signal-card AMD --provider local-fixture --llm none --output json
```

The command emits `signaldesk.web.signal_card_presentation.v1` by fetching the canonical TA report, extracting its nested `signal_card`, and building renderer-facing sections. It is intentionally JSON-only so downstream UI code consumes the same grouped facts, levels, events, risk, unavailable context, scores, and provenance that backend code already validates.


## Provider status rendering contract

The provider status dashboard slice is represented by `signaldesk.web.provider_status_presentation.v1`:

```bash
signaldesk web provider-status --mode default --output json
```

The command resolves the requested provider mode and groups declared provider capabilities for UI sections. It does not run live checks, read credentials, or infer provider availability. Missing enhanced roles remain explicit in `unavailable_context`, preserving the default-mode contract when paid keys are absent.


## Chart overlay rendering contract

The chart overlay dashboard slice is represented by `signaldesk.web.chart_overlay_presentation.v1`:

```bash
signaldesk web chart-overlays AMD --provider local-fixture --llm none --output json
```

The command groups canonical signal-card levels into horizontal chart overlays, backend events into markers, trend regimes into badges, and risk/unavailable/provenance rows into separate renderer sections. It does not calculate moving averages, infer missing levels, fetch extra candles, or hide unavailable context; empty overlay sections mean the backend did not emit that context.


## Watchlist scan rendering contract

The watchlist scan dashboard slice is represented by `signaldesk.web.watchlist_scan_presentation.v1`:

```bash
signaldesk web watchlist-scan --watchlist watchlists/default.yaml --provider local-fixture --llm none --output json
```

The command reuses the canonical watchlist report payload, then groups ranked setup rows, failed/skipped rows, provider unavailable context, and provenance for renderer consumption. Ranking, scores, confirmation/invalidation levels, risk, and unavailable context remain backend-emitted facts; dashboard code must not rescore symbols, infer missing levels, or hide provider gaps.
