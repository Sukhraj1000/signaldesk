# MarketSearch Architecture

## Purpose

MarketSearch is an open-source, TA-first market intelligence sandbox.

It fetches market data, runs deterministic technical analysis, optionally enriches with facts/catalysts, and produces daily signal cards. It is not a live trading bot.

## High-Level Diagram

```text
                 ┌──────────────────────┐
                 │   CLI / Dashboard    │
                 │  Daily Reports / API │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │   Discovery Agent    │
                 │ watchlists / movers  │
                 └──────────┬───────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────┐
│                 Provider Layer                       │
│ yfinance / Stooq / FMP / Polygon / CCXT / CoinGecko │
└──────────┬───────────────────────────────┬───────────┘
           │                               │
           ▼                               ▼
┌──────────────────────┐        ┌──────────────────────┐
│  Price History Data  │        │  Facts / Catalysts   │
│ OHLCV / Quote Data   │        │ news / earnings etc. │
└──────────┬───────────┘        └──────────┬───────────┘
           │                               │
           ▼                               ▼
┌──────────────────────┐        ┌──────────────────────┐
│       TA Agent       │        │   Catalyst Agent     │
│ RSI / MA / Fib etc.  │        │ facts / signals      │
└──────────┬───────────┘        └──────────┬───────────┘
           │                               │
           └───────────────┬───────────────┘
                           ▼
                 ┌──────────────────────┐
                 │      Risk Agent      │
                 │ liquidity / trend    │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │     Report Agent     │
                 │ cards / briefs / UI  │
                 └──────────────────────┘
```

## Core Principle

The system is deterministic first and agentic second.

- Code calculates prices, indicators, support/resistance, Fibonacci levels, and risk flags.
- LLMs explain structured facts only.
- Missing provider data is shown as unavailable, not treated as proof that no risk exists.

## Main Components

### Provider Layer

Pluggable market-data adapters.

Examples:

- yfinance / Stooq for open-source basics
- FMP for richer private/enhanced mode
- Polygon / Twelve Data / Alpha Vantage for optional paid data
- CCXT / CoinGecko for crypto

### TA Agent

Calculates technical structure from OHLCV data.

Includes:

- moving averages
- RSI / MACD / ATR
- support and resistance
- Fibonacci retracements
- breakout/breakdown detection
- confirmation/invalidation levels

### Catalyst Agent

Adds context when data is available.

Examples:

- news
- earnings
- filings
- fundamentals
- analyst data
- sector/peer context

### Risk Agent

Flags reasons not to chase.

Examples:

- illiquidity
- overextension
- failed breakout
- weak/no catalyst
- below key trend levels
- upcoming earnings risk

### Report Agent

Creates useful outputs:

- CLI table
- JSON
- Markdown report
- dashboard cards

## Open Source vs Enhanced Mode

### Open-source mode

Focuses on:

- historical candles
- latest quotes
- technical analysis
- chart overlays
- signal cards
- optional BYO LLM

### FMP-enhanced/private mode

Adds:

- earnings
- financials
- analyst estimates
- company facts
- richer news/catalyst attribution

## First Milestone

```bash
marketsearch ta AMD --provider yfinance --llm none
```

Expected output:

- trend
- setup label
- RSI
- moving averages
- support/resistance
- Fibonacci levels
- confirmation level
- invalidation level
- risk flags
- data provenance
