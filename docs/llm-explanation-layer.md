# LLM explanation layer

SignalDesk keeps market intelligence deterministic first. The optional LLM explanation layer may only turn already-structured SignalDesk facts into readable narrative. It must not fetch market data, call tools, invent prices, levels, catalysts, fundamentals, risks, or recommendations.

## Supported modes

- Default mode: `--llm none` / `LLM_PROVIDER=none`. The TA report remains complete and useful without any paid key or LLM provider. Narrative is reported as unavailable context.
- Enhanced LLM mode: OpenAI-compatible request payloads can be generated and validated locally, but provider calls must pass through the guarded prompt and fail-closed response parser before narrative is attached.


## Adapter configuration boundary

Enhanced LLM adapter settings are loaded from environment variables but only non-secret configuration is reported by `signaldesk config inspect`:

- `LLM_PROVIDER` selects optional explanation mode; default remains `none`.
- `LLM_MODEL` defaults to `openai/gpt-4o-mini`.
- `LLM_ENDPOINT_URL` defaults to the OpenRouter chat-completions endpoint and is redacted if userinfo is present.
- `LLM_API_KEY` is held in `Settings.llm_api_key` only for the live adapter call, with `repr=False`, and is never printed by config inspection; config inspection reports only whether a non-blank key is configured.

Default/no-LLM workflows do not require any of these enhanced-mode variables. Live adapter calls must still pass through the guarded prompt and fail-closed response parser before narrative is attached.

## Guarded input boundary

Use the CLI inspection commands to see the exact JSON sent to a future adapter without calling an LLM:

```bash
signaldesk llm input-schema
signaldesk llm output-schema
signaldesk llm prompt-payload AMD --provider local-fixture --llm none
signaldesk llm chat-request AMD --provider local-fixture --llm none
signaldesk llm prompt-payload AMD --provider local-fixture --llm openrouter
signaldesk llm chat-request AMD --provider local-fixture --llm openrouter
```

The `openrouter` and `openai` selections on these `signaldesk llm` inspection commands do not call a provider or attach narrative. They only mark the canonical signal card and provider-mode metadata for guarded enhanced-mode prompt/request inspection; unavailable context still states that live narrative generation was not performed. User-facing TA commands may opt into live enhanced LLM narrative generation with `--llm openrouter` or `--llm openai` only when `LLM_API_KEY` is configured. Default `--llm none` remains complete and does not require paid keys.

The prompt payload contains only:

- `schema_version` and `task`
- fixed guardrails
- paths that label provider/news text as untrusted data
- paths intentionally excluded from prompt construction, especially prior narrative
- a validated `signal_card` with `narrative: null`
- the strict `signaldesk.llm_explanation.v1` output schema

Adapters must not add browser tools, market-data clients, hidden free-form context, or provider text outside the structured `signal_card`. Provider and news strings remain untrusted data even when they contain instruction-like text. Before an OpenAI-compatible chat request is rendered, SignalDesk revalidates the complete prompt payload so mutated guardrails, output schemas, untrusted-field labels, excluded fields, or recycled narrative fail closed.

## Live TA explanation boundary

Live TA narrative generation is explicit enhanced mode:

```bash
LLM_API_KEY=... signaldesk ta AMD --provider local-fixture --llm openrouter --output markdown
```

The TA command first builds the deterministic signal card, then sends only the guarded prompt payload through the OpenAI-compatible adapter. The provider response must parse as strict `signaldesk.llm_explanation.v1` JSON before narrative is attached. If `LLM_API_KEY` is missing, the command fails closed with a configuration error and points users back to default `--llm none`; it must not silently omit unavailable LLM context or fabricate narrative.

## Fail-closed output boundary

Candidate model output must be raw JSON matching `signaldesk.llm_explanation.v1`. Validate or render it locally before attaching it to a report:

```bash
signaldesk llm validate-output fixtures/llm/valid-explanation.json
signaldesk llm validate-chat-response fixtures/llm/valid-chat-response.json
signaldesk llm render-output fixtures/llm/valid-explanation.json
signaldesk llm attach-output AMD fixtures/llm/valid-explanation.json --provider local-fixture --output markdown
```

Invalid JSON, Markdown fences, extra fields, blank required fields, malformed OpenAI-compatible chat responses, and tool-call style responses fail closed at the raw-JSON/schema boundary. Recommendation-language terms covered by `signaldesk_backend.llm._reject_recommendation_language` also fail closed during field validation. Each `deterministic_facts_used` entry must resolve to an existing scalar path in the exact prompt/report signal card; when a reviewer-friendly `path=value` suffix is supplied, the value must match the resolved signal-card value, using numeric comparison for numerically equivalent values and string comparison otherwise, instead of merely pointing at a real path. `signaldesk llm attach-output` reuses the same parser before it can add narrative to a deterministic TA report; failed validation emits a generic schema failure and does not leak hostile model text. Unavailable provider or LLM context must remain visible to users instead of being silently omitted.

## Reviewer checklist for issue #54

When reviewing LLM-related PRs, confirm that:

- deterministic TA facts, levels, scores, provenance, risks, and unavailable context remain source of truth;
- default mode still works with open data and no LLM key;
- prompt inputs are structured JSON only;
- malicious provider/news text cannot override guardrails;
- parsed model output is schema-validated before narrative attachment;
- missing provider or LLM data is shown as unavailable context.
