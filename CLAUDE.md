# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Quick Start

### Backend
```bash
cd backend
pip install -r requirements.txt
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
python3 -m pytest -q
```

### Frontend
```bash
cd frontend
npm install
npm run dev
npm run lint
```

## Architecture

### Backend (FastAPI + SQLAlchemy)

**Request lifecycle:**
1. FastAPI receives REST request
2. Route handler opens a DB session via `get_db()`
3. Engine / feed / bot code runs **without touching the DB directly**
4. Session is closed after response

**Invariant:** The event loop / engine core never opens its own SQLAlchemy sessions. All persistence goes through the request-scoped `get_db()` dependency or explicitly passed sessions.

**Core components:**
- `main.py` – FastAPI app with 9 REST endpoints, CORS middleware, lifespan startup/shutdown
- `settings.py` – Pydantic-settings config (env-prefixed `CTA_`), `.env` supported
- `config.py` – Backward-compat shim exporting `settings` values
- `database.py` – SQLAlchemy engine, `SessionLocal`, `get_session()`, `init_db()`, `close_db()`
- `models.py` – ORM: `Asset`, `PriceTicker`, `Portfolio`, `TradeLog`, `Candle`, `Strategy`, `PortfolioAccount`, `Position`, `Fill`, `Order`, `Signal`, `EquitySnapshot`
- `bot.py` – Legacy compatibility shim (`run_bot_cycle`, `get_signal`, `start_bot`, `execute_trade`, `prune_old_prices`); actual trading logic lives in `engine/`
- `feeds/` – Market data ingestion (Coinbase, Binance, synthetic, recorder, backfill, validation, manager)
- `engine/` – Paper trading engine (`core.py`), broker (`paper_broker.py`), risk (`risk.py`), portfolio (`portfolio.py`), metrics (`metrics.py`), market state (`market_state.py`)
- `strategies/` – Trading strategies

**Startup sequence (lifespan):**
1. `init_db()` — create tables
2. `backfill_candles()` — REST backfill for recent candles
3. `MARKET.warm_from_db()` — warm in-memory state from DB
4. `start_bot()` — legacy APScheduler bot cycle
5. `feed_manager.start()` — live WebSocket streaming
6. `candle_flusher_task()` — background task flushing closed candles to DB
7. `legacy_price_syncer_task()` — background task syncing ticks to legacy `PriceTicker` table

**Shutdown sequence (reverse):**
1. Stop APScheduler
2. Cancel background tasks
3. Final candle flush
4. `feed_manager.stop()`
5. `close_db()`

### Frontend (React + Vite + TypeScript)

**Stack:** React 18, Vite 5, TypeScript 5, Axios, React Router 6, Zustand 4, ESLint.

**Entry:** `src/main.tsx` → `src/App.tsx`

**State:** `src/store.ts` — Zustand store with `fetchAll()`, `executeTrade()`, and per-endpoint selectors.

**HTTP:** `src/api.ts` — Axios instance pointing to `http://localhost:8000`.

**Components:**
- `Dashboard.tsx` — Top-level layout
- `PriceTable.tsx` — Historical price data
- `Portfolio.tsx` — User holdings
- `TradeForm.tsx` — Manual trade entry

**Routes:** React Router (basic setup in `App.tsx`).

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Provider + mode status |
| GET | `/assets` | List all assets |
| GET | `/assets/{symbol}` | Get single asset |
| GET | `/prices` | Recent price tickers (newest-first, max 100) |
| GET | `/portfolio` | List all portfolio positions |
| GET | `/portfolio/{symbol}` | Get single position |
| POST | `/trade` | Execute BUY/SELL trade |
| GET | `/trades` | Trade log (paginated, max 1000) |
| GET | `/bot/signals` | Current signals per asset |

**Request validation:** Pydantic `Field(pattern=...)` for symbols/types; `ge=0` for quantity.

**Response model:** Separate Pydantic response models; SQLAlchemy models stay in `models.py`.

## Data Model

### Legacy tables
| Table | Columns | Notes |
|-------|---------|-------|
| `assets` | `id`, `symbol`, `name` | Static seed data |
| `prices` | `id`, `symbol`, `price`, `timestamp` | Legacy ticker table, synced from `MARKET` |
| `portfolios` | `symbol` (PK), `balance`, `quantity`, `cost_basis` | Legacy per-coin portfolio |
| `trades_legacy` | `id`, `type`, `symbol`, `quantity`, `price`, `timestamp` | Legacy trade log |

### Engine tables
| Table | Columns | Notes |
|-------|---------|-------|
| `strategies` | `id`, `key`, `name`, `description`, `enabled`, `params_json`, `starting_cash`, `created_at` | |
| `portfolios` | `id`, `strategy_id` (FK), `cash`, `realized_pnl`, `fees_paid`, `peak_equity`, `is_halted`, `halt_reason`, `updated_at` | One per strategy |
| `positions` | `id`, `strategy_id` (FK), `symbol`, `quantity`, `avg_entry_price`, `stop_loss_price`, `take_profit_price`, `opened_at`, `updated_at` | |
| `orders` | `id`, `strategy_id` (FK), `client_order_id` (unique), `symbol`, `side`, `type`, `status`, `quantity`, `limit_price`, `stop_price`, `filled_quantity`, `filled_price`, `fee`, `reject_reason`, `time_in_force`, `created_at`, `updated_at` | |
| `fills` | `id`, `strategy_id` (FK), `order_id`, `client_order_id`, `symbol`, `side`, `quantity`, `price`, `fee`, `order_type`, `ts` | Append-only |
| `candles` | `id`, `symbol`, `interval`, `open_time` (UK), `open`, `high`, `low`, `close`, `volume`, `trades`, `source` | 1m bars |
| `equity_snapshots` | `id`, `strategy_id` (FK), `ts`, `equity`, `cash`, `position_value`, `realized_pnl`, `unrealized_pnl`, `drawdown_pct` | |
| `signals` | `id`, `strategy_id` (FK), `symbol`, `action`, `strength`, `price`, `indicators_json`, `ts` | |

**Indexes:** `prices.symbol`, `candles.(symbol, interval, open_time)` (unique + desc index), `equity_snapshots.ts`.

## Engine Design

### MarketState (thread-safe hot state)
- In-memory last-tick price, tick history (`deque` per symbol, maxlen 600)
- Open/closed 1m candle aggregation
- `drain_closed_candles()` returns rolled candles for DB flush
- `close_all_candles()` forces close on provider switch/shutdown

### PaperBroker
- MARKET: taker fill at mid + spread/2 + slippage
- LIMIT: maker fill when crossed
- STOP: triggers on last price, converts to MARKET
- Fees: taker 10 bps / maker 4 bps
- Rejects: insufficient cash/position, below min notional, max positions, stale price, non-tradable symbol

### RiskManager
- `size_order()`: risk 2% of equity / stop distance, capped at 20% notional, floored at min notional ($10)
- SL 2% / TP 4% attached on entry
- Max open positions: 4
- Cooldown: 3 bars after close
- Kill-switch: drawdown > 25% → halt + flatten

### Metrics
- Pure functions over fills + equity snapshots
- `win_rate`, `avg_win`, `avg_loss`, `profit_factor`, `max_drawdown_pct`, `intraday_sharpe`, `trade_count`, `avg_hold_time_seconds`
- H1/H10: all divisions guarded via `_safe_div`; never returns inf/NaN

## Feeds

### Providers
- **Coinbase** — REST backfill + WebSocket ticker
- **Binance** — REST backfill + WebSocket ticker
- **Synthetic** — OU/GBM random walk for offline testing

### Manager
- Auto-failover: primary → secondary on repeated failure
- Failback probe every 120s
- Per-tick validation (H1: NaN/Inf/stale; H4: sanity band with confirmation)

### Validation
- Reject NaN/Inf/non-positive prices
- Reject stale (>20s) or future timestamps
- H4: reject single-tick moves >10% unless 2 consecutive confirmations

## Python Constraints

- **Target:** Python 3.9+
- **No f-strings in logging** — use `%` formatting to avoid `AttributeError` on custom log handlers
- **Decimal-safe:** convert SQLAlchemy `Numeric` to `float` before arithmetic
- **Thread safety:** `MarketState` uses `threading.RLock`; engine core uses its own lock
- **Async boundaries:** only `main.py` and `feeds/` use `async/await`; engine/bot are synchronous

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `CTA_DATABASE_URL` | `sqlite:///./crypto.db` | DB connection string |
| `CTA_CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173,...` | Comma-separated allowed origins |
| `CTA_SYMBOLS` | `BTC,ETH,SOL,XRP,ADA,DOGE,AVAX,LINK` | Traded symbols |
| `CTA_STARTING_CASH` | `100000.0` | Default strategy equity |
| `CTA_HOST` | `127.0.0.1` | Bind address (set `0.0.0.0` for LAN) |

## Commands

```bash
# Backend
cd backend
pip install -r requirements.txt
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
python3 -m pytest -q
python3 -m pytest tests/test_engine_core.py -v

# Frontend
cd frontend
npm install
npm run dev
npm run lint
npm run build
```

## Notes for Future Work

- **WebSocket:** `docs/WS_PROTOCOL.md` is planned (step 41); no WS endpoint exists yet
- **Frontend tests:** No Jest/Vitest configured yet; `store/selectors`, `api/ws`, `Watchlist`, `OrderTicket`, `ErrorBoundary` need coverage
- **Legacy bot:** `bot.py` is a compatibility shim; the engine in `engine/core.py` is the production path
