# LLM explanation layer

SignalDesk keeps market intelligence deterministic first. The optional LLM explanation layer may only turn already-structured SignalDesk facts into readable narrative. It must not fetch market data, call tools, invent prices, levels, catalysts, fundamentals, risks, or recommendations.

## Supported modes

- Default mode: `--llm none` / `LLM_PROVIDER=none`. The TA report remains complete and useful without any paid key or LLM provider. Narrative is reported as unavailable context.
- Enhanced LLM mode: OpenAI-compatible request payloads can be generated and validated locally, but provider calls must pass through the guarded prompt and fail-closed response parser before narrative is attached.

## Guarded input boundary

Use the CLI inspection commands to see the exact JSON sent to a future adapter without calling an LLM:

```bash
signaldesk llm input-schema
signaldesk llm output-schema
signaldesk llm prompt-payload AMD --provider local-fixture --llm none
signaldesk llm chat-request AMD --provider local-fixture --llm none
```

The prompt payload contains only:

- `schema_version` and `task`
- fixed guardrails
- paths that label provider/news text as untrusted data
- paths intentionally excluded from prompt construction, especially prior narrative
- a validated `signal_card` with `narrative: null`
- the strict `signaldesk.llm_explanation.v1` output schema

Adapters must not add browser tools, market-data clients, hidden free-form context, or provider text outside the structured `signal_card`. Provider and news strings remain untrusted data even when they contain instruction-like text. Before an OpenAI-compatible chat request is rendered, SignalDesk revalidates the complete prompt payload so mutated guardrails, output schemas, untrusted-field labels, excluded fields, or recycled narrative fail closed.

## Fail-closed output boundary

Candidate model output must be raw JSON matching `signaldesk.llm_explanation.v1`. Validate or render it locally before attaching it to a report:

```bash
signaldesk llm validate-output fixtures/llm/valid-explanation.json
signaldesk llm validate-chat-response fixtures/llm/valid-chat-response.json
signaldesk llm render-output fixtures/llm/valid-explanation.json
```

Invalid JSON, Markdown fences, extra fields, blank required fields, malformed OpenAI-compatible chat responses, and tool-call style responses fail closed at the raw-JSON/schema boundary. Recommendation-language terms covered by `signaldesk_backend.llm._reject_recommendation_language` also fail closed during field validation. Unavailable provider or LLM context must remain visible to users instead of being silently omitted.

## Reviewer checklist for issue #54

When reviewing LLM-related PRs, confirm that:

- deterministic TA facts, levels, scores, provenance, risks, and unavailable context remain source of truth;
- default mode still works with open data and no LLM key;
- prompt inputs are structured JSON only;
- malicious provider/news text cannot override guardrails;
- parsed model output is schema-validated before narrative attachment;
- missing provider or LLM data is shown as unavailable context.
