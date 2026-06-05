# MarketSearch Roadmap

## 1. Project Foundation

### 1.1 Repository setup

- Create monorepo structure
- Add Python backend package
- Add CLI package
- Add future web app folder
- Add `.env.example`
- Add basic README

### 1.2 Tooling

- Configure Python 3.12+
- Add Ruff
- Add pytest
- Add type checking
- Add GitHub Actions CI
- Add Docker Compose for local Postgres/Redis later

---

## 2. Core Domain Models

### 2.1 Market data models

- Create Candle model
- Create Quote model
- Create Symbol model
- Create ProviderResult model
- Create ProviderCapability model

### 2.2 Analysis models

- Create TechnicalSnapshot model
- Create KeyLevels model
- Create TechnicalEvent model
- Create SignalCard model
- Create Provenance model

---

## 3. Provider Layer

### 3.1 Provider interface

- Define common provider interface
- Add provider registry
- Add capability reporting
- Add provider health check command

### 3.2 Open-source providers

- Add yfinance adapter
- Add Stooq fallback adapter
- Add local CSV adapter

### 3.3 Enhanced providers

- Add FMP adapter
- Add Polygon/Twelve Data placeholder adapters
- Add CCXT/CoinGecko crypto adapters later

### 3.4 Provider safety

- Add API key loading from env
- Redact credentials in logs
- Add rate-limit handling
- Add fallback handling

---

## 4. Technical Analysis Engine

### 4.1 Indicators

- Implement SMA/EMA
- Implement RSI
- Implement MACD
- Implement ATR
- Implement volume average / relative volume

### 4.2 Levels

- Detect swing highs/lows
- Detect support/resistance zones
- Calculate Fibonacci retracements
- Calculate confirmation/invalidation levels

### 4.3 Events

- Detect reclaimed/lost moving averages
- Detect breakout/breakdown
- Detect failed breakout
- Detect bounce/rejection
- Detect overextension

### 4.4 Testing

- Add fixture candle data
- Add unit tests for indicators
- Add unit tests for levels
- Add unit tests for event detection

---

## 5. Agent Layer

### 5.1 Discovery Agent

- Load watchlists
- Accept manual symbols
- Add simple mover/volume scan later

### 5.2 TA Agent

- Consume candles
- Run technical engine
- Return TechnicalSnapshot
- Work without any LLM

### 5.3 Catalyst Agent

- Start with basic news support
- Add FMP earnings/fundamentals when key exists
- Separate facts, signals, opinion, and unavailable context

### 5.4 Risk Agent

- Add liquidity checks
- Add trend risk checks
- Add overextension checks
- Add missing-data warnings

### 5.5 Report Agent

- Generate JSON output
- Generate CLI table output
- Generate Markdown report

---

## 6. CLI MVP

### 6.1 Provider commands

- `marketsearch providers check`
- `marketsearch providers list`

### 6.2 TA commands

- `marketsearch ta AMD --provider yfinance --llm none`
- Support JSON output
- Support Markdown output
- Support terminal table output

### 6.3 Scan commands

- `marketsearch scan --watchlist watchlists/default.yaml`
- Rank symbols by setup quality
- Show risk flags and invalidation levels

---

## 7. LLM Integration

### 7.1 LLM provider abstraction

- Add `LLM_PROVIDER=none`
- Add OpenAI-compatible adapter
- Add OpenRouter/OpenAI support
- Add Ollama/local support later

### 7.2 Guardrails

- LLM receives structured facts only
- LLM cannot invent prices or catalysts
- LLM output must separate facts/signals/opinion
- Add tests for prompt input/output shape

---

## 8. Reports and Scheduling

### 8.1 Daily reports

- Generate daily watchlist report
- Include top setups
- Include risk warnings
- Include unavailable context

### 8.2 Scheduling

- Add local cron example
- Add worker job later
- Persist report runs later

---

## 9. Dashboard

### 9.1 API

- Add FastAPI service
- Add endpoints for quote/candles/TA/signal cards

### 9.2 Web app

- Add React/Vite app
- Add signal card view
- Add symbol analysis page
- Add provider status page

### 9.3 Charts

- Add KLineChart candlestick view
- Overlay moving averages
- Overlay support/resistance
- Overlay Fibonacci levels
- Show confirmation/invalidation lines

---

## 10. Backtesting

### 10.1 Strategy rules

- Add breakout strategy
- Add pullback-in-uptrend strategy
- Add failed-breakout strategy
- Add reversal-watch strategy

### 10.2 Backtest engine

- Add vectorbt integration
- Run strategy over fixture universe
- Generate basic performance report

---

## 11. First Build Targets

### Target 1: Single-symbol TA

```bash
marketsearch ta AMD --provider yfinance --llm none
```

Must return:

- trend
- RSI
- moving averages
- support/resistance
- Fibonacci levels
- setup label
- confirmation/invalidation
- risk flags

### Target 2: Enhanced single-symbol TA

```bash
marketsearch ta AMD --provider fmp --llm openrouter
```

Must add:

- earnings context
- richer company facts
- catalyst notes
- LLM-written explanation from structured facts

### Target 3: Watchlist scan

```bash
marketsearch scan --watchlist watchlists/default.yaml
```

Must return:

- ranked setups
- key levels
- risk warnings
- unavailable context

---

## 12. Non-Goals for MVP

Do not build yet:

- live trading
- broker execution
- portfolio auto-rebalancing
- screenshot-based chart analysis
- complex real-time websocket engine
- Kubernetes/microservices
- paid data redistribution
