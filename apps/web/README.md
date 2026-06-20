# SignalDesk Web

Placeholder for the future web application.

The web app should be a presentation adapter over canonical SignalDesk API/JSON output. It must not become a second implementation of technical analysis.

## Future purpose

The dashboard should help users inspect:

- provider status
- single-symbol signal cards
- watchlist scan results
- chart overlays for moving averages, levels, events, confirmation, and invalidation
- risk flags and unavailable context
- report history once persistence exists

## Design principles

- Feed UI components from canonical `SignalCard`/API output.
- Keep facts, signals, risks, unavailable context, and optional narrative visually distinct.
- Make provider mode visible: default yfinance/basic mode vs enhanced FMP/richer mode.
- Do not hide missing catalysts or fundamentals.
- Avoid chart clutter and false precision.
- No dashboard-only analysis logic.

## Future acceptance criteria

- dashboard renders fixture signal cards
- `/health` or equivalent app smoke is tested
- chart overlays are derived from backend level/event models
- visual tests or screenshots are added once UI becomes active
