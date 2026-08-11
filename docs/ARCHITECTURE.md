# Architecture

## Overview

CryptoTradeApp is a paper-trading terminal that ingests live market data from Coinbase/Binance, runs automated trading strategies against virtual cash, and exposes REST endpoints for a React frontend. No broker account is connected — everything is simulated in-process.

## Concurrency Model

The backend runs **two concurrent worlds** that must never deadlock:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI / Uvicorn                            │
│                    (async event loop, single thread)                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │  REST handler │    │  lifespan()  │    │  background tasks    │  │
│  │  (async)      │    │  (async)      │    │  (asyncio tasks)     │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────┬───────────┘  │
│         │                   │                        │              │
│         ▼                   ▼                        ▼              │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              get_db() → Session (request-scoped)             │   │
│  │         yield/close per request. Never shared across tasks.  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    Engine / Bot (sync, own threads)                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌────────────────┐      ┌─────────────────────────────────────┐   │
│  │  APScheduler   │      │         PaperEngine (sync)          │   │
│  │  bot_job()     │─────▶│  - Own threading.Lock              │   │
│  │  (thread pool) │      │  - Never opens DB sessions         │   │
│  └────────────────┘      │  - Reads MARKET (thread-safe)      │   │
│                           │  - Calls broker.apply_fill()       │   │
│  ┌────────────────┐      │  - Returns Fill objects for        │   │
│  │  engine_tick() │      │    caller to persist               │   │
│  │  (1s loop)     │─────▶│                                    │   │
│  │                │      └─────────────────────────────────────┘   │
│  └────────────────┘                                                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    Shared Hot State (thread-safe)                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ┌─────────────────┐      ┌──────────────────────────┐           │
│   │   MarketState    │◄─────│  FeedManager (async)      │           │
│   │  - RLock         │      │  - Coinbase/Binance WS     │           │
│   │  - last_ticks    │      │  - Synthetic fallback      │           │
│   │  - tick_history  │      │  - Validates every tick    │           │
│   │  - open_candles  │      └──────────────────────────┘           │
│   └────────┬────────┘                                               │
│            │                                                        │
│            ▼                                                        │
│   ┌─────────────────┐      ┌──────────────────────────┐           │
│   │  PaperBroker     │      │  RiskManager              │           │
│   │  - Reads MARKET  │      │  - Stateless between calls│           │
│   │  - Returns Fill  │      │  - size_order()            │           │
│   └─────────────────┘      └──────────────────────────┘           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                         SQLite Database                             │
│                   (accessed only via get_session())                 │
└─────────────────────────────────────────────────────────────────────┘
```

## Invariant: Event Loop Never Touches the DB

The async event loop (FastAPI handlers, background tasks, feed manager) **must never** open its own SQLAlchemy session. All database access flows through:

1. **Request-scoped dependency:** `get_db()` in route handlers
2. **Explicitly passed sessions:** Engine / bot functions receive a `Session` parameter from the caller

This prevents:
- Cross-thread session sharing
- Hidden DB writes from async callbacks
- Transaction ambiguity between HTTP requests and background tasks

## Thread Safety

| Component | Lock | Rationale |
|-----------|------|-----------|
| `MarketState` | `threading.RLock` | Shared across async feeds and sync engine ticks |
| `PaperEngine` | `threading.Lock` | Protects `_working_orders` and account mutations |
| `PortfolioAccount` | None (caller-serialized) | Engine serializes all `apply_fill()` calls |
| SQLAlchemy `Session` | Scoped per request | SQLite allows one writer at a time |

## Data Flow

### Tick Ingestion (async)

```
FeedProvider (WS/REST)
    │
    ▼
validate_tick() ──► H1 (NaN/Inf/stale) + H4 (sanity band)
    │
    ▼
MARKET.on_tick() ──► thread-safe state update
    │
    ├──► candle aggregation
    │
    └──► engine_tick() callback (queued, runs in engine thread)
```

### Order Lifecycle (sync)

```
Strategy / REST /test
    │
    ▼
engine.submit_order()
    │
    ├──► RiskManager.size_order() ──► returns qty + SL/TP
    │
    ├──► PaperBroker.execute_market() / check_limit_fill() / check_stop_trigger()
    │       │
    │       ├──► PortfolioAccount.apply_fill() ──► mutates cash/positions
    │       │
    │       └──► returns Fill object
    │
    ├──► persist Fill + Order + Position + EquitySnapshot (caller does this)
    │
    └──► return Fill to caller
```

## WebSocket Protocol (Planned)

No WS endpoint exists yet. When implemented, the planned topic table is:

| Topic | Direction | Payload | Notes |
|-------|-----------|---------|-------|
| `ticks.{symbol}` | Server → Client | `{symbol, price, bid, ask, ts, source}` | 4 Hz broadcast |
| `candles.{symbol}` | Server → Client | `{symbol, interval, o, h, l, c, v, open_time}` | On bar close |
| `signals.{symbol}` | Server → Client | `{symbol, action, strength, price, ts}` | On strategy signal |
| `orders.{strategy_id}` | Server → Client | `{order_id, status, filled_qty, filled_price}` | Order lifecycle |
| `equity.{strategy_id}` | Server → Client | `{equity, cash, position_value, drawdown_pct}` | 30s snapshot |

**Connection lifecycle:**
1. Client connects to `/ws`
2. Server sends `connected` + current snapshot
3. Client subscribes to topics via `subscribe` messages
4. Server pushes updates; client can `unsubscribe`
5. On disconnect, server cleans up subscriptions after 30s

## Python Constraints

- **Target:** Python 3.9+
- **No f-strings in logging** — use `%` formatting to avoid `AttributeError` on custom log handlers
- **Decimal-safe:** convert SQLAlchemy `Numeric` to `float` before arithmetic
- **Thread safety:** `MarketState` uses `threading.RLock`; engine core uses its own lock
- **Async boundaries:** only `main.py` and `feeds/` use `async/await`; engine/bot are synchronous

## Frontend Constraints

- **Target:** React 18 + Vite 5 + TypeScript 5
- **State:** Zustand 4 (centralized store in `src/store.ts`)
- **HTTP:** Axios with base URL `http://localhost:8000`
- **No real broker:** all trades are simulated by the backend
