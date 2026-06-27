# CLI JSON contract

`signaldesk ta <SYMBOL> --llm none --output json` emits a versioned JSON object for deterministic technical analysis. When `--provider` is omitted, the command resolves the price provider from `--mode default|enhanced`; an explicit `--provider <provider>` still overrides role-mode resolution for targeted smoke checks.

The current schema is `signaldesk.ta.v1`. It keeps backward-compatible top-level fields for early CLI consumers, but the durable contract is grouped by category so downstream tools do not confuse facts, deterministic signals, risk framing, provenance, unavailable context, or optional narrative.

## Top-level contract sections

- `schema_version`: schema identifier for the CLI TA JSON object.
- `facts`: directly observed or request-scoped facts, such as symbol, provider, interval, candle count, latest timestamp, and latest close. In enhanced mode this may also include `fundamentals` and `catalysts` objects; those objects are provider-sourced context with provider attribution and timestamps, not deterministic TA signals.
- `provider_mode`: resolved provider-role metadata for the run, including mode, price provider, optional fundamentals provider, optional catalyst provider, and optional LLM provider.
- `deterministic_signals`: values calculated by SignalDesk deterministic code from the candle series. This currently includes indicators, regimes, deterministic technical events, swing levels, confirmation level, and invalidation level.
- `risks`: deterministic risk or scope notes with `kind`, `severity`, `message`, and `source`. The TA path currently flags scope limits, insufficient history, unknown regimes, missing invalidation levels, unavailable enhanced context, high volatility, low-volume/liquidity, trend conflicts, and overextension events from already-computed facts. Missing enhanced data must not be interpreted as no risk.
- `scores`: deterministic `setup_quality`, `risk`, and `data_quality` scores bounded from 0 to 100, each with traceable reason codes, source rules, messages, and weights. Decimal values are serialized as strings, matching the rest of the TA JSON contract.
- `provenance`: provider/source/timeframe/input/generated-at metadata for the data used to compute the output.
- `unavailable_context`: context that is unavailable in the current mode, such as fundamentals in the default TA path or LLM narrative when `--llm none` is selected.
- `llm` and `narrative`: LLM mode metadata. Narrative is `null` until guarded LLM explanation mode is implemented.

## Enhanced context fields

When configured providers return enhanced context, `facts.fundamentals` contains the canonical company-fact fields documented by the schema: `symbol`, `provider`, `generated_at`, `company_name`, `exchange`, `industry`, `sector`, `market_cap`, `currency`, `price`, `beta`, `pe_ratio`, `eps`, and `source_url`. Nullable values mean the provider did not supply that fact; they are not filled by inference.

`facts.catalysts` contains `symbol`, `provider`, `generated_at`, and an `events` array. Each event includes `headline`, `provider`, `published_at`, `source`, `url`, and `summary`. Missing or stale timestamps are surfaced through provenance warnings or unavailable context rather than silently converted into recommendations.

## Provider mode behavior

Default mode remains useful without paid keys. Enhanced provider or LLM fields must be optional, fixture-backed in tests, or reported as unavailable context rather than silently omitted.

The golden CLI test in `tests/test_cli.py` protects the current `signaldesk.ta.v1` shape with fixture-backed data, so CI does not require live provider network or paid credentials.

## LLM prompt and output validation contracts

LLM explanation mode is intentionally adapter-only around canonical signal cards. The deterministic TA and scan paths remain complete when `--llm none` is selected, and missing narrative stays in `unavailable_context` rather than being treated as an all-clear.

Current no-network inspection commands are:

```bash
signaldesk llm prompt-payload AMD --provider local-fixture --output json
signaldesk llm chat-messages AMD --provider local-fixture --output json
signaldesk llm validate-output path/to/candidate-llm-output.json
```

`signaldesk llm prompt-payload` emits `signaldesk.llm_prompt.v1`, containing only:

- explicit guardrails that prohibit fetching market data, inventing prices/levels/catalysts/fundamentals, or making recommendations;
- the validated canonical `signal_card`, with any prior `signal_card.narrative` reset to `null` and listed in `excluded_signal_card_fields` so generated narrative text is not fed back as instructions;
- labels for provider/news fields that must be treated as untrusted quoted data;
- a strict `signaldesk.llm_explanation.v1` output schema.

`signaldesk llm chat-messages` wraps the same guarded payload in OpenAI-compatible `system`/`user` messages for adapter smoke checks, without exposing tools, provider clients, hidden market context, or credentials.

`signaldesk llm validate-output` is a fail-closed boundary for candidate LLM JSON. It accepts only the schema-versioned explanation object with `summary`, `deterministic_facts_used`, `risks`, and `unavailable_context`; unexpected fields such as recommendations are rejected. Validation errors are intentionally generic so hostile or provider-sourced text from an invalid LLM response is not echoed back into terminal output, logs, or reports.

The machine-readable prompt payload schema lives at [`docs/schemas/signaldesk.llm_prompt.v1.schema.json`](schemas/signaldesk.llm_prompt.v1.schema.json), and the explanation output schema lives at [`docs/schemas/signaldesk.llm_explanation.v1.schema.json`](schemas/signaldesk.llm_explanation.v1.schema.json). The backend prompt payload embeds this same strict output schema so adapter prompts, CLI validation, and documentation stay aligned.

Future OpenAI-compatible or local LLM adapters should call these same backend contracts before and after provider invocation. `parse_openai_compatible_chat_response()` is the no-network adapter boundary for OpenRouter/OpenAI-compatible responses: it accepts exactly one assistant message choice as raw JSON, rejects tool calls, and validates the explanation schema before narrative attachment. Adapters must not receive provider clients, tool handles, hidden market context, credentials, or authority to override unavailable context from external text.


## Backtest setup replay JSON

`signaldesk backtest setup-labels --output json` emits `signaldesk.backtest.setup_labels.v1`, a no-network discovery payload listing deterministic built-in setup labels that SignalDesk can derive from historical candles. It also includes setup_label_details with each label derivation rule name, human-readable description, lookback candle count, and minimum candle count needed before the rule can produce a signal. The list is intentionally research-only metadata and includes a limitation that labels are not recommendations, orders, broker instructions, or live trading behavior.

`signaldesk backtest setup <SYMBOL> --setup-label <LABEL> --signal-index <N> --output json` emits `signaldesk.backtest.setup_replay.v1`, a deterministic research report for one historical setup label. In default mode the command uses `local-fixture` when no provider is passed, keeping the smoke path no-network and useful without paid keys.

`signaldesk backtest setup-batch <SYMBOL> --output json` emits `signaldesk.backtest.setup_batch.v1`, a batch envelope evaluating every built-in deterministic setup label over the same candle history. The top-level envelope includes `symbol`, `timeframe`, `candle_count`, `data_start`, `data_end`, `provider`, `source`, `summary`, `labels`, and `limitations`. The `summary` includes evaluated/unavailable label counts, total derived signals, evaluation coverage, average data availability across evaluated labels, the best evaluated setup label by deterministic event usefulness, and that best label's `best_event_usefulness` decimal string. Summary rankings are historical research only, and unavailable labels remain unavailable context rather than negative setup evidence. Each entry in `labels` contains its `setup_label`, `status`, `setup_label_detail` with derivation/lookback/minimum-candle metadata, `signal_indices`, nested single-label `report` when evaluated, and explicit `unavailable_context`. Labels with no matching historical candles remain present with `status: "no_signals"`; candle sets shorter than the setup derivation lookback use `status: "insufficient_history"` instead of being reported as a true no-match.

Each nested evaluated `report` contains:

- `setup_label`, `symbol`, `timeframe`, `sample_size`, `evaluable_signals`, and evaluated `horizons`.
- `metrics`: hit rate, average forward return by horizon, false breakout rate, max adverse excursion proxy, event usefulness, and data availability rate. Decimal values are serialized as strings, and unavailable metric values are `null`.
- `observations`: one row per supplied signal index, including the observed candle timestamp, entry close, forward returns by horizon, hit/false-breakout flags, and max adverse excursion proxy.
- `walk_forward_windows`: chronological signal-count windows for walk-forward style validation, each with its own sample size, evaluable count, and usefulness metrics. Use `--walk-forward-window-size` to split windows; otherwise the full replay is reported as one window.
- `provenance`: provider, source, generated timestamp, timeframe, inputs, and warnings.
- `limitations` and `unavailable_context`: required explicit report sections so missing forward windows or scope limits are visible instead of silently omitted.

Backtest setup replay is research-only. The JSON schemas deliberately have no broker, order, fill, position-sizing, slippage, recommendation, or live-trading fields. The setup-label discovery schema lives at [`docs/schemas/signaldesk.backtest.setup_labels.v1.schema.json`](schemas/signaldesk.backtest.setup_labels.v1.schema.json), the single-label replay schema lives at [`docs/schemas/signaldesk.backtest.setup_replay.v1.schema.json`](schemas/signaldesk.backtest.setup_replay.v1.schema.json), and the batch envelope schema lives at [`docs/schemas/signaldesk.backtest.setup_batch.v1.schema.json`](schemas/signaldesk.backtest.setup_batch.v1.schema.json).

## TA and watchlist Markdown reports

`signaldesk ta <SYMBOL> --llm none --output markdown` renders a compact human-readable report from the same canonical `signal_card` object used by JSON output. The Markdown report separates facts, deterministic signals, risks, unavailable context, provenance, and optional narrative state. It includes the generated timestamp, price provider, latest observed close, explicit missing enhanced/LLM context, and provider/source/timeframe/input/generated-at provenance without introducing LLM-derived facts or extra provider data.

`signaldesk report --watchlist <PATH> --format markdown` renders each successful watchlist entry from the same signal-card summary boundaries. Per-symbol report sections must keep optional narrative state separate from facts and deterministic signals: with `--llm none`, the report shows `LLM: none` and `Narrative: unavailable` instead of fabricating explanation text.


The machine-readable schema for the canonical signal-card envelope lives at [`docs/schemas/signaldesk.ta.v1.schema.json`](schemas/signaldesk.ta.v1.schema.json). It is intentionally limited to the durable renderer-facing sections and keeps early flat compatibility fields as additional top-level properties.

## Signal-card section aliases

The v1 JSON keeps early flat and grouped fields for compatibility, then adds canonical signal-card sections so future CLI/API/dashboard/reporting renderers can share one object:

- `identity`: symbol, timeframe, generated timestamp, and schema version.
- `trend`: moving-average, momentum, and regime summaries from deterministic calculations.
- `levels`: support, resistance, Fibonacci placeholder, confirmation, and invalidation fields.
- `events`: deterministic event list; mirrors `technical_events`.
- `risk`: deterministic flags and unavailable context together for card rendering.
- `score`: deterministic score breakdowns for setup quality, risk, and data quality.
- `signal_card`: one canonical nested card object that groups `identity`, `provider_mode`, `facts`, `trend`, `levels`, `events`, `risk`, `score`, `provenance`, `unavailable_context`, and LLM narrative metadata for renderers that should consume a single object.

The canonical aliases do not introduce new data sources or LLM-derived facts; they regroup already-computed deterministic output and unavailable-context metadata. The top-level compatibility fields remain available while downstream adapters migrate to `signal_card`.



## Guarded LLM prompt payload

`signaldesk llm input-schema --output json` renders the guarded prompt payload schema, and `signaldesk llm prompt-payload <SYMBOL> --provider local-fixture --output json` emits the guarded prompt payload without calling an LLM provider, which gives CI and developers a runtime smoke path for explanation-mode boundaries. Optional LLM explanation mode must use the backend `build_ta_llm_prompt_payload()` helper rather than building prompts directly from provider responses. The helper first validates the canonical `signal_card`, deep-copies that structured card, removes any prior narrative text from the prompt input, labels provider/news text fields as untrusted data, and attaches fixed guardrails plus a fail-closed JSON output schema. It does not include provider clients, tools, credentials, or permission to fetch market data.

This preserves the TA-first contract: deterministic code remains the source of truth for prices, levels, events, risks, scores, provenance, and unavailable context. LLM adapters may explain those structured facts only, and invalid/missing provider data must stay visible as unavailable context instead of being converted into recommendations.

## Watchlist scan JSON

`signaldesk scan --watchlist <path> --output json` emits a deterministic watchlist scan payload for ranked multi-symbol TA workflows. The payload is assembled from the same canonical TA signal-card summaries as `signaldesk ta`; the scan command does not introduce separate market-data facts or LLM-derived conclusions.

The scan JSON object includes:

- `watchlist`: source watchlist path.
- `watchlist_model`: normalized watchlist metadata (`name`, `symbols`, `tags`, `asset_class`, `provider_preference`, `enabled`, and `notes`).
- `scanned_at`: UTC scan timestamp shared by all symbols in the run.
- `provider_mode`: resolved role/provider metadata, including unavailable enhanced context where relevant.
- `symbols`: normalized, de-duplicated requested symbols in watchlist order.
- `results`: per-symbol outcomes in watchlist order. Successful rows have `status: "ok"` plus a deterministic `summary`; failures have `status: "failed"` plus a redacted `error`; disabled watchlists return `status: "skipped"` rows with a reason.
- `ranked_setups`: successful results sorted deterministically by setup quality, risk score, then symbol, each with a `rank`.
- `failed_symbols`: all failed symbol rows, preserving watchlist order so one bad symbol does not hide the rest of the scan.
- `skipped_symbols`: skipped rows, currently used when the normalized watchlist is disabled.

Default scan mode remains usable without paid keys. For no-network fixture smoke checks, use a watchlist whose `provider_preference` is `local-fixture` or pass `--provider local-fixture`; missing enhanced context must appear as unavailable context rather than being interpreted as absent risk.

## Watchlist report JSON

`signaldesk report --watchlist <path> --format json` emits the same deterministic watchlist payload used by the Markdown report renderer. The JSON object includes `watchlist`, `watchlist_model`, `scanned_at`, `provider_mode`, `symbols`, `results`, `ranked_setups`, `failed_symbols`, and `skipped_symbols`. Successful results include a `summary` with provider, deterministic TA summary fields, the canonical nested `signal_card`, provenance, and unavailable context; failed results include a redacted `error` string. This keeps report automation machine-readable without introducing extra data sources or LLM-derived facts, and lets downstream renderers consume the same card sections as `ta --output json`.
