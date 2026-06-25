# SignalDesk API

The API package exposes a small HTTP surface for web and dashboard clients without duplicating market-analysis logic. This initial slice includes:

- `GET /health` for runtime smoke checks.
- `GET /providers` for backend provider capability metadata.
- `GET /symbols/{symbol}/ta` for the canonical `signaldesk.ta.v1` technical-analysis JSON contract shared with the CLI.
- `GET /openapi.json` for generated OpenAPI documentation.

Run locally after installation:

```bash
signaldesk-api serve --host 127.0.0.1 --port 8000
```

Print the OpenAPI document without starting a server:

```bash
signaldesk-api openapi
```
