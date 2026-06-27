# Backtesting and evaluation

SignalDesk backtesting is deterministic setup-rule research. It replays setup labels over historical candle data to measure whether a rule was useful in prior data; it does not model or imply broker execution, orders, fills, position sizing, slippage, recommendations, or live trading behavior.

## Supported runtime surface

The current default-mode commands are fixture-backed and require no paid provider keys or network access:

```bash
signaldesk backtest setup-labels --output json
signaldesk backtest setup AMD --setup-label breakout_watch --horizon 1 --horizon 5 --provider local-fixture --output json
signaldesk backtest setup-batch AMD --horizon 1 --horizon 5 --provider local-fixture --output json
```

`setup-labels` lists the built-in deterministic labels that can be derived from candles and reports the rule metadata needed to evaluate them historically, including derivation name, lookback candles, and minimum candle count. `setup` evaluates one label, either from explicit `--signal-index` values or by deriving built-in labels from historical candles when no signal index is passed. `setup-batch` evaluates every built-in label over one shared candle history so users can compare rule availability and usefulness without mixing provider runs. Its top-level `summary` ranks only evaluated labels by deterministic `event_usefulness` and keeps labels with no signals or insufficient history counted as unavailable context, not as negative evidence or recommendations. Each batch label row carries `setup_label_detail` derivation/lookback metadata so users can see the rule that was attempted even when no historical signals are available.

## Metrics

Backtest reports include the roadmap metrics for historical setup usefulness:

- `hit_rate`: share of evaluable setup observations that produced a positive primary forward return, or touched the optional confirmation level when one is supplied.
- `average_forward_return_by_horizon`: average forward return for each requested candle horizon. Missing forward windows are `null` for that horizon.
- `false_breakout_rate`: share of observations that confirmed and then touched the optional invalidation level when both levels are supplied.
- `max_adverse_excursion`: worst forward low versus the setup close across evaluated observations.
- `event_usefulness`: deterministic composite of available average returns, hit rate, and inverse false-breakout rate.
- `data_availability_rate`: share of requested signal/horizon windows that had enough future candle history.
- Batch `summary`: evaluated/unavailable label counts, total derived signals, average data availability across evaluated labels, and the best evaluated setup label by `event_usefulness`. Summary rankings are historical research only and are not recommendations.

When `--walk-forward-window-size` is provided, reports also include chronological walk-forward windows with the same metric shape. This keeps validation explicitly historical and avoids tuning a rule only on one aggregate sample.

## Unavailable context and limitations

Missing forward candles, insufficient history, or labels with no matching historical candles are surfaced as unavailable context in the JSON/table output. Missing data must not be interpreted as a negative fact such as `no risk` or `no catalyst`; it only means SignalDesk could not evaluate that context from the available candle history.

The batch payload keeps every supported setup label in the response. A label can be:

- `evaluated` when matching signal indices were found and replayed;
- `no_signals` when history was long enough but the deterministic rule did not match;
- `insufficient_history` when there were not enough candles for the derivation lookback.

## Contract files

Machine-readable contracts live in [`schemas/signaldesk.backtest.setup_labels.v1.schema.json`](schemas/signaldesk.backtest.setup_labels.v1.schema.json), [`schemas/signaldesk.backtest.setup_replay.v1.schema.json`](schemas/signaldesk.backtest.setup_replay.v1.schema.json), and [`schemas/signaldesk.backtest.setup_batch.v1.schema.json`](schemas/signaldesk.backtest.setup_batch.v1.schema.json). The CLI JSON contract summary is in [`cli-json-contract.md`](cli-json-contract.md).
