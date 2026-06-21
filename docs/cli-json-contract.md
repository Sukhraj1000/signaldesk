# CLI JSON contract

`signaldesk ta <SYMBOL> --llm none --output json` emits a versioned JSON object for deterministic technical analysis. When `--provider` is omitted, the command resolves the price provider from `--mode default|enhanced`; an explicit `--provider <provider>` still overrides role-mode resolution for targeted smoke checks.

The current schema is `signaldesk.ta.v1`. It keeps backward-compatible top-level fields for early CLI consumers, but the durable contract is grouped by category so downstream tools do not confuse facts, deterministic signals, risk framing, provenance, unavailable context, or optional narrative.

## Top-level contract sections

- `schema_version`: schema identifier for the CLI TA JSON object.
- `facts`: directly observed or request-scoped facts, such as symbol, provider, interval, candle count, latest timestamp, and latest close.
- `provider_mode`: resolved provider-role metadata for the run, including mode, price provider, optional fundamentals provider, optional catalyst provider, and optional LLM provider.
- `deterministic_signals`: values calculated by SignalDesk deterministic code from the candle series. This currently includes indicators, regimes, deterministic technical events, swing levels, confirmation level, and invalidation level.
- `risks`: deterministic risk or scope notes. Missing enhanced data must not be interpreted as no risk.
- `scores`: deterministic `setup_quality`, `risk`, and `data_quality` scores bounded from 0 to 100, each with traceable reason codes, source rules, messages, and weights. Decimal values are serialized as strings, matching the rest of the TA JSON contract.
- `provenance`: provider/source/timeframe/input metadata for the data used to compute the output.
- `unavailable_context`: context that is unavailable in the current mode, such as fundamentals in the default TA path or LLM narrative when `--llm none` is selected.
- `llm` and `narrative`: LLM mode metadata. Narrative is `null` until guarded LLM explanation mode is implemented.

## Provider mode behavior

Default mode remains useful without paid keys. Enhanced provider or LLM fields must be optional, fixture-backed in tests, or reported as unavailable context rather than silently omitted.

The golden CLI test in `tests/test_cli.py` protects the current `signaldesk.ta.v1` shape with fixture-backed data, so CI does not require live provider network or paid credentials.
