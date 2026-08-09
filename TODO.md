# TODO — CryptoTradeApp → Live Paper-Trading Terminal

> **Goal:** turn the current demo skeleton into a real trading terminal — live market data,
> multi-strategy paper-trading bots, and a dynamic dashboard showing live P&L.
> Everything is real (ticks, indicators, orders, fills, fees, slippage, P&L) except that
> **no broker account is connected** — the cash is virtual.
>
> The previous version of this file is obsolete: 13 of its 15 items were already implemented.
> Only "env-based config with pydantic-settings" survived, and it lives in **Phase 1, step 8** below.

---

## ⚠️ Read before writing any code

### 1. The runtime is Python 3.9.6 — not 3.12

`backend/pyproject.toml` claims `requires-python = ">=3.12"` and is **wrong**.
`/usr/bin/python3` is 3.9.6. A single `str | None` runtime annotation crashes the app at import.

**Banned:**

| Don't write | Write instead |
| --- | --- |
| `def f(x: str \| None)` | `def f(x: Optional[str])` |
| `list[str]`, `dict[str, int]` (in annotations) | `List[str]`, `Dict[str, int]` |
| `datetime.UTC` | `timezone.utc` |
| `async with asyncio.TaskGroup()` | `asyncio.gather()` + explicit `task.cancel()` |
| `match x:` | `if/elif` |
| `import tomllib` | `tomli` or skip |

### 2. There is no git repo

Nothing is under version control, and this plan **deletes** `bot.py`, `config.py`, four React
components, `QUICKSTART.md`, and `FIXES_SUMMARY.md`. Phase 0 is what makes that recoverable.
**Do not skip it.**

### 3. The one architectural invariant

> **The event loop never touches the database.**

Async feed → in-memory `MarketState` (lock-guarded). Sync scheduler threads read from it and own
all DB writes. Engine events reach WS clients via a bounded `queue.Queue`, drained by an async task.
Raw ticks (~13/s) **never** hit disk.

```
┌── asyncio loop (uvicorn) ──────────────────────────────────┐
│ FeedManager   → WS → Tick → MARKET.on_tick()   (in-memory) │
│ Broadcast 4Hz → MARKET.take_dirty() → Hub.publish          │
│ EventDrain 10Hz → EVENT_BUS.get_nowait() → Hub.publish     │
│ /ws endpoint (async) · REST (sync → anyio threadpool)      │
└────────────────────────────────────────────────────────────┘
┌── APScheduler threads (own all DB writes) ─────────────────┐
│ engine_tick    1s → SL/TP + working limit orders           │
│ strategy_tick 15s → evaluate on CLOSED bars only           │
│ candle_flush   5s → drain closed candles → upsert          │
│ equity_snap   30s · prune 1h                               │
└────────────────────────────────────────────────────────────┘
```

### Already installed (verified) — do not reinstall

`fastapi 0.128.8` · `sqlalchemy 2.0.51` · `pydantic 2.11.4` · `websockets 12.0` ·
`httpx 0.28.1` · `pytest 8.4.2` · `anyio 4.9` · `numpy` · `pandas` · `orjson`

**Baseline test suite: 31 passing.** Keep it green through Phase 0.

---

## Phase 0 — Safety net & tooling

**Effort: S · Leaves the app: byte-identical, but versioned and with working scripts**

- [ ] **1. Initialise git and commit the baseline**
  ```bash
  cd /Users/developer/Projects/CryptoTradeApp
  git init
  git add -A && git commit -m "chore: baseline before live-data rewrite"
  ```
  This is the only thing that makes later deletions safe.

- [ ] **2. Create the root `.gitignore`, then untrack what shouldn't be committed**
  Contents: `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.venv/`, `venv/`, `*.db`, `*.db-journal`,
  `*.db-wal`, `*.db-shm`, `node_modules/`, `dist/`, `.env`, `.DS_Store`, `coverage/`
  ```bash
  git rm -r --cached frontend/dist backend/crypto.db backend/.pytest_cache
  find . -name .DS_Store -exec git rm --cached {} +
  git commit -m "chore: add gitignore, untrack build artifacts"
  ```

- [ ] **3. Fix `backend/run.sh`** — currently hardcodes `cd /app/CryptoTradeApp/backend`
  (a container path that does not exist on this machine) and launches on **port 15678**
  while every doc and the Vite proxy say 8000.
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  cd "$(dirname "$0")"
  exec python3 -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" --reload
  ```

- [ ] **4. Fix `frontend/run.sh`** the same way → `npm run dev -- --port "${PORT:-3355}"`

- [ ] **5. Add `/Users/developer/Projects/CryptoTradeApp/dev.sh`** — starts both servers,
  `trap 'kill 0' INT TERM` so Ctrl-C kills the whole process group. `chmod +x` all three scripts.

- [ ] **6. Fix `backend/pyproject.toml`**
  - `requires-python = ">=3.9"` (match reality)
  - Delete the stray `edition = "2021"` key — a Cargo-ism, meaningless in `[project]`

- [ ] **7. Add the missing dependencies to `backend/requirements.txt`** and mirror into `pyproject.toml`
  > `pytest` and `httpx` are used by the test suite but declared **nowhere** — the suite
  > currently cannot be installed from `requirements.txt` alone.

  Add: `pytest>=8`, `pytest-asyncio>=0.24`, `httpx>=0.27`, `websockets>=12`, `pydantic-settings>=2.5`
  Then add `asyncio_mode = auto` to `backend/pytest.ini`.

**✅ Phase 0 gate:** `cd backend && python3 -m pytest -q` → **31 passed**. `./dev.sh` starts both servers.

---

## Phase 1 — Config, schema, and the live feed

**Effort: L · Leaves the app: existing UI, but showing 8 real live prices from Coinbase**

### 1a · Configuration

- [ ] **8. Create `backend/settings.py` with `pydantic-settings`** *(the one surviving item from the old TODO)*

  `class Settings(BaseSettings)` with `SettingsConfigDict(env_file=".env", env_prefix="CTA_", extra="ignore")`
  and `@lru_cache def get_settings()` — this finally uses the abandoned `lru_cache` import
  sitting unused in `config.py`.

  > **Gotcha:** pydantic-settings parses `List[str]` from env as **JSON**. Add a
  > `@field_validator("symbols", "feed_providers", "cors_origins", mode="before")` that splits a
  > plain string on commas, so `CTA_SYMBOLS=BTC,ETH,SOL` works instead of requiring `'["BTC",...]'`.

  Fields — feed: `feed_providers`, `feed_stale_seconds=20`, `feed_reconnect_base_seconds=1.0`,
  `feed_reconnect_max_seconds=30.0`, `feed_failback_seconds=120`, `backfill_candles=300` ·
  cadence: `broadcast_hz=4.0`, `candle_flush_seconds=5`, `engine_tick_seconds=1`,
  `strategy_interval_seconds=15`, `equity_snapshot_seconds=30` ·
  money: `starting_cash=100000.0`, `taker_fee_bps=10.0`, `maker_fee_bps=4.0`, `slippage_bps=1.5`,
  `impact_notional=50000.0`, `min_notional=10.0` ·
  risk: `max_open_positions=4`, `max_position_pct=0.20`, `risk_per_trade_pct=0.02`,
  `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `max_drawdown_pct=0.25` ·
  retention: `candle_retention_days=7`, `equity_retention_hours=48`

- [ ] **9. Create `backend/.env.example`** documenting every `CTA_*` var. `.env` itself stays gitignored.

- [ ] **10. Create `backend/feeds/symbols.py`** — the single symbol registry, replacing `config.ASSETS`
  ```python
  SYMBOLS = {
    "BTC":  {"name":"Bitcoin",  "coinbase":"BTC-USD",  "binance":"BTCUSDT",
             "price_dp":2, "qty_dp":6, "seed":65000, "vol":0.55},
    "ETH":  {"name":"Ethereum", "coinbase":"ETH-USD",  "binance":"ETHUSDT",
             "price_dp":2, "qty_dp":5, "seed":1925,  "vol":0.65},
    # SOL, XRP, ADA, DOGE, AVAX, LINK
  }
  ```
  Helpers: `to_provider(symbol, provider)`, `from_provider(pid, provider)`, `is_tradable(symbol)`.

- [ ] **11. Reduce `backend/config.py` to a ~15-line back-compat shim** deriving `ASSETS`,
  `CORS_ORIGINS`, `SCHEDULER_INTERVAL` from `get_settings()`, so existing imports in `bot.py`,
  `main.py`, and `conftest.py` keep working mid-refactor. **Delete it in Phase 3, step 36.**

### 1b · Schema

- [ ] **12. Rewrite `backend/models.py`**
  - `class Base(DeclarativeBase)` — kills the `MovedIn20Warning` from `declarative_base()`
  - **`class UtcDateTime(TypeDecorator)`** — `impl = DateTime(timezone=True)`, `cache_ok=True`;
    bind converts to UTC and rejects naive, result attaches `timezone.utc`.
    Use it for **every** timestamp column. *(Today every `DateTime` is naive while tz-aware values
    are written — SQLite silently drops the tzinfo.)*
  - All money/qty columns `Numeric(20, 8, asdecimal=False)` → the ORM returns real floats,
    so the **~40 scattered `float()` wrappers** in `main.py` and `bot.py` all disappear.

  | table | columns |
  | --- | --- |
  | `meta` | `key` PK, `value` — holds `schema_version` |
  | `assets` | `id`, `symbol` UNIQUE, `name`, `display_order`, `is_active` |
  | `candles` | `id`, `symbol`, `interval`, `open_time`, `open`, `high`, `low`, `close`, `volume`, `trades`, `source`; `UniqueConstraint(symbol, interval, open_time)`; `Index(symbol, interval, open_time.desc())` |
  | `strategies` | `id`, `key` UNIQUE, `name`, `description`, `enabled`, `params_json`, `starting_cash`, `created_at` |
  | `portfolios` | `id`, `strategy_id` FK UNIQUE, `cash`, `realized_pnl`, `fees_paid`, `peak_equity`, `is_halted`, `halt_reason`, `updated_at` |
  | `positions` | `id`, `strategy_id` FK, `symbol`, `quantity`, `avg_entry_price`, `realized_pnl`, `stop_loss_price`, `take_profit_price`, `opened_at`, `updated_at`; `UniqueConstraint(strategy_id, symbol)` |
  | `orders` | `id`, `client_order_id` UNIQUE, `strategy_id`, `symbol`, `side`, `order_type`, `quantity`, `limit_price`, `stop_price`, `time_in_force`, `status`, `filled_quantity`, `avg_fill_price`, `reason`, `reject_reason`, `created_at`, `updated_at` |
  | `fills` | `id`, `order_id` FK, `strategy_id`, `symbol`, `side`, `quantity`, `price`, `fee`, `realized_pnl`, `mark_price`, `liquidity`, `ts` |
  | `equity_snapshots` | `id`, `strategy_id`, `ts`, `equity`, `cash`, `position_value`, `realized_pnl`, `unrealized_pnl`, `drawdown_pct` |
  | `signals` | `id`, `strategy_id`, `symbol`, `action`, `strength`, `price`, `indicators_json`, `ts` |

  **Deleted:** `PriceTicker` → `candles` · `Portfolio` → `portfolios` + `positions` · `TradeLog` → `orders` + `fills`

- [ ] **13. Fix the `Portfolio.balance` semantics** *(design note — implemented in step 20)*
  > Today the coin row's `balance` is *decremented* by cost on BUY (goes negative = "invested")
  > and *incremented* by revenue on SELL — but on a full exit, `quantity` and `cost_basis` reset to 0
  > while `balance` keeps an unreset residual that accidentally approximates realized P&L.
  > It is never labelled, never reset, and impossible to reason about.

  Replaced by explicit state: `portfolios.cash` (free USD) · `positions.quantity` / `avg_entry_price`
  · `realized_pnl` as a real accumulator. **Equity is never a column** — always derived as
  `cash + Σ qty × mark`.

- [ ] **14. Rewrite `backend/database.py`**
  - **Keep** `NullPool` + `check_same_thread=False` and **keep the existing comment** — it documents
    a real, hard-won race between the scheduler thread and FastAPI's threadpool.
  - **Add WAL pragmas via `@event.listens_for(engine, "connect")`:**
    ```python
    PRAGMA journal_mode=WAL;  PRAGMA busy_timeout=5000;  PRAGMA synchronous=NORMAL;
    ```
    **Non-negotiable** — three writer threads on SQLite without WAL will throw `database is locked`.
  - Rewrite `init_db()`: create tables → read `meta.schema_version` → on absent/mismatch,
    `drop_all()` + `create_all()` + **log a loud `SCHEMA RESET` warning** → seed `assets` from
    `SYMBOLS` and `strategies` + `portfolios` from the strategy registry.
  - **Delete the 180-row synthetic price seeding** and its buggy `.replace(minute=...)` logic
    (it only mutates the minute field, so "60 minutes of history" is scattered inside the current
    hour with some timestamps in the future). Startup becomes idempotent.
  - **Decision: drop-and-recreate, no Alembic.** `crypto.db` holds only synthetic junk.

### 1c · The feed layer

- [ ] **15. Create `backend/feeds/base.py`** — frozen dataclass
  `Tick(symbol, price, ts, source, bid, ask, volume_24h, change_24h_pct, seq)` and
  `class MarketFeed(ABC)` with `name`, `async def stream(symbols) -> AsyncIterator[Tick]`,
  `async def healthy() -> bool`.

- [ ] **16. Create `backend/feeds/coinbase.py`** — **payload verified live from this machine**
  - URL `wss://advanced-trade-ws.coinbase.com` — no API key
  - Subscribe `{"type":"subscribe","product_ids":["BTC-USD",...],"channel":"ticker"}`,
    plus a second subscribe on `"channel":"heartbeats"` to keep the socket alive when quiet
  - Message:
    ```json
    {"channel":"ticker","sequence_num":3,"events":[{"type":"update","tickers":[
      {"product_id":"BTC-USD","price":"65172.63","best_bid":"65172.63","best_ask":"65172.64",
       "price_percent_chg_24_h":"0.28321903","volume_24_h":"2927.08"}]}]}
    ```
  - `sequence_num` is monotonic per connection → a gap means log + force reconnect
  - Health probe: `GET https://api.exchange.coinbase.com/products/BTC-USD/ticker`
  - All 8 target symbols confirmed streaming; ~13 ticker updates/sec across them

- [ ] **17. Create `backend/feeds/binance.py`** — **payload verified live**
  - URL `wss://stream.binance.com:9443/stream?streams=btcusdt@ticker/ethusdt@ticker/...`
    Fallback host: `wss://data-stream.binance.vision/...` (market-data mirror)
  - Message:
    ```json
    {"stream":"btcusdt@ticker","data":{"s":"ETHUSDT","c":"1926.11","b":"1926.11","a":"1926.12",
     "P":"0.200","v":"69233.10","E":1786311922016}}
    ```
    `c`=last · `b`/`a`=best bid/ask · `P`=24h % · `v`=base volume · `E`=event ms
  - **Use `@ticker` (1/s/symbol), not `@trade`** — trade streams are 20–50 msg/s on BTC alone
    for zero added value at top-of-book.
  - Health probe: `GET https://api.binance.com/api/v3/ping`
  - **Binance is USDT-quoted (~5bp basis vs USD).** Tag `source`, and surface the provider in the UI.

- [ ] **18. Create `backend/feeds/synthetic.py`** — GBM with mean reversion toward
  `SYMBOLS[s]["seed"]`, per-symbol annualised vol, 2 Hz emission, seedable via `CTA_SYNTHETIC_SEED`
  for deterministic tests. **This retires `bot.py:generate_mock_price`**
  (which despite its name is a deterministic oscillator flipping on `timestamp.minute % 2`).

- [ ] **19. Create `backend/feeds/backfill.py`** — real chart history on first paint, via `httpx.AsyncClient`
  - Coinbase: `GET https://api.exchange.coinbase.com/products/{pid}/candles?granularity=60`
    → `[[time, low, high, open, close, volume], ...]`, newest-first, ≤300 rows, no auth
    > ⚠️ **Field order is `low` before `high`, `open` before `close`** — verified, and easy to get wrong.
  - Binance: `GET /api/v3/klines?symbol=..&interval=1m&limit=500`
  - Upsert via `sqlalchemy.dialects.sqlite.insert(...).on_conflict_do_update(...)`
  - **250 ms stagger between symbols**, and **skip entirely if the newest stored candle is < 2 min old**
    — protects against `--reload` re-running startup on every code save and getting IP-banned.

- [ ] **20. Create `backend/feeds/manager.py`** — `FeedManager`
  - Priority chain from `settings.feed_providers` (`coinbase,binance,synthetic`)
  - Reconnect backoff `min(cap, base·2^attempt) × U(0.5, 1.5)`, base 1s cap 30s;
    after 3 failed attempts, demote to the next provider
  - **Staleness watchdog** — no tick for any symbol in `feed_stale_seconds` (20s) ⇒ treat the socket
    as dead and fail over.
    > This is the failure mode that actually happens: a WebSocket that stays *open* and goes silent.
    > Connection state will not detect it.
  - **Failback probe** every 120s: if `active != providers[0]` and `providers[0].healthy()`,
    cancel and promote. Cooldown prevents flapping.
  - On provider switch, **close the in-progress candle** and start fresh tagged with the new `source`
    — never blend USD and USDT prints in one bar.
  - Publishes `FeedStatus{status, provider, mode: LIVE|DEGRADED|SIM, since, last_tick_age_ms, reconnects}`

### 1d · Concurrency wiring

- [ ] **21. Create `backend/engine/market_state.py`** — `MarketState` (module singleton `MARKET`),
  guarded by one `threading.RLock`:
  `on_tick(tick) -> Optional[Candle]` (returns a closed candle on bucket rollover) ·
  `last(symbol)` · `snapshot()` · `age_seconds(symbol)` · `recent_ticks(symbol, n)`
  (`deque(maxlen=600)` per symbol, powers the tape) · `open_candle(symbol)` ·
  `drain_closed_candles()` · `take_dirty() -> Set[str]`.
  Plus `CandleAggregator` with `bucket(ts) = ts.replace(second=0, microsecond=0)`.

- [ ] **22. Create `backend/engine/events.py`** — bounded `EVENT_BUS = queue.Queue(maxsize=2000)`
  and `emit(topic, type, data)`. Thread-safe by construction, drops oldest on overflow, never raises
  if the loop is closed.
  > Chosen over `asyncio.run_coroutine_threadsafe` because it cannot blow up during shutdown
  > and gives natural bounded backpressure.

- [ ] **23. Rewrite the `lifespan` in `backend/main.py`**
  Startup: `init_db()` → `await backfill(symbols)` → `MARKET.warm_from_db()` →
  `PaperEngine.load_from_db()` → `asyncio.create_task` × (feed, broadcast, event-drain) →
  `start_scheduler()`.
  Shutdown reverses: `scheduler.shutdown(wait=True)` → cancel tasks with
  `asyncio.gather(*tasks, return_exceptions=True)` → final candle flush → `close_db()`.

- [ ] **24. Keep the old REST endpoints alive as thin shims** over the new model
  (`/prices`, `/portfolio`, `/portfolio/{symbol}`, `/trades`, `/bot/signals`, `POST /trade`)
  so **the existing frontend keeps rendering — now on real prices.**

- [ ] **25. Remove `run_bot_cycle(db)` from the `POST /trade` handler** (`main.py:200`)
  — it mutates prices mid-request and can trigger bot trades inside a user's request.
  This is why `test_trade_buy_then_sell_roundtrip` has such loose assertions.

- [ ] **26. Delete `generate_mock_price` from `bot.py`.** Keep `execute_trade`'s weighted-average
  cost-basis block (~lines 85–92) — it gets ported verbatim in Phase 2, step 27.

**✅ Phase 1 gate**
- `curl localhost:8000/prices` → real BTC near market price, **not 45000**
- `curl localhost:8000/health` → `provider: coinbase`
- Disconnect network → within 20s the feed flips to synthetic and prices keep moving;
  reconnect → fails back to Coinbase within 120s
- Old UI at `localhost:3355` still renders

---

## Phase 2 — Paper trading engine + multi-strategy

**Effort: L · Leaves the app: four live paper portfolios trading real prices**

- [ ] **27. Create `backend/engine/portfolio.py`** — `PortfolioAccount`, in-memory authoritative
  hot state per strategy (the DB is a durable log). **Port the weighted-average cost-basis logic
  from `bot.py:execute_trade` lines ~85–92 verbatim** into `apply_fill`.
  - **BUY:** `cash -= qty·price + fee`; `avg_entry = (qty₀·avg₀ + qty·price + fee) / (qty₀ + qty)`
    — **fees capitalised into cost basis**
  - **SELL:** `realized = qty·(price − avg_entry) − fee`; `cash += qty·price − fee`;
    `avg_entry` unchanged until `qty == 0`, then reset
  - **The accounting identity, enforced by a property test in step 60:**
    ```
    equity == starting_cash + realized_pnl + unrealized_pnl     (exactly)
    ```
    Capitalising buy fees is what makes this hold. It is also standard broker convention.

- [ ] **28. Create `backend/engine/paper_broker.py`** — `PaperBroker`
  - Reference `mid = (bid+ask)/2` else `last`; `spread = max(ask−bid, mid·2bps)`
  - MARKET BUY `= mid + spread/2 + slip`, SELL `= mid − spread/2 − slip`, where
    `slip = mid·(slippage_bps/1e4)·(1 + min(2.0, notional/impact_notional))`
  - Fees: taker 10 bps / maker 4 bps, always USD
  - LIMIT BUY fills when `ask ≤ limit`, at `min(limit, ask)`, MAKER, no slippage; SELL mirrors
  - STOP (backs SL/TP) triggers on `last` and converts to MARKET ⇒ realistically models stop slippage
  - Rejections: `INSUFFICIENT_CASH`, `INSUFFICIENT_POSITION`, `BELOW_MIN_NOTIONAL`, `MAX_POSITIONS`,
    `STRATEGY_HALTED`, `NO_MARKET_DATA`, `STALE_PRICE` (mark > 30s old), `SYMBOL_NOT_TRADABLE`
  - **Cut: partial fills** (top-of-book can't model queue position — the `filled_quantity` column
    stays for future use). **Cut: shorting/margin** — long-only, stated in the docs.

- [ ] **29. Create `backend/engine/risk.py`** — `RiskManager`
  - `size_order()`: risk 2% of equity against the stop distance, capped by `max_position_pct` (20%)
    and floored at `min_notional` ($10)
  - `max_open_positions` = 4 · SL 2% / TP 4% attached on entry · optional trailing stop ·
    `COOLDOWN_BARS = 3` per symbol after a close
  - **Max-drawdown kill-switch:** `equity < peak_equity·0.75` ⇒ flatten all at market,
    `is_halted=1`, `halt_reason='MAX_DRAWDOWN'`, emit `strategy.halted`. Resumable via API.

- [ ] **30. Create `backend/engine/core.py`** — `PaperEngine`: one `PortfolioAccount` per
  `strategies.id`, all mutations funnelled through
  `submit_order(client_order_id, strategy, symbol, side, type, qty, ...)` under a single `RLock`.
  **Manual REST orders and bot orders call the same method — one code path, no divergence.**
  `on_tick_batch()` (the 1s job) evaluates working limits + SL/TP and marks to market.

- [ ] **31. Create `backend/engine/metrics.py`** — return %, win rate, avg win/loss, profit factor,
  max drawdown, intraday Sharpe (**label it as such** — 30s sampling is noisy), trade count,
  avg hold time. Computed from `fills` + `equity_snapshots`.

- [ ] **32. Create `backend/strategies/indicators.py`** — pure-Python `sma`, `ema`, `rsi` (Wilder),
  `atr`, `donchian`, `stddev`, `macd`.
  > **No numpy/pandas.** 200 bars × 8 symbols × 3 strategies every 15s is microseconds, and a
  > dependency-free module is far easier to unit-test against reference vectors.

- [ ] **33. Create `backend/strategies/base.py` + `registry.py`** —
  `StrategyContext(symbol, candles, last_price, position, cash, equity, params)`,
  `Decision(action, strength, reason, indicators)`, a `Strategy` protocol
  (`key`, `name`, `default_params`, `warmup_bars`, `evaluate(ctx) -> Decision`),
  and a `@register` decorator populating `STRATEGIES: Dict[str, Strategy]`.

- [ ] **34. Implement the three strategies**
  - `sma_crossover.py` — SMA(9)/SMA(21) golden/death cross. **Direct generalisation of `bot.py:compute_ma`.**
  - `rsi_reversion.py` — RSI(14) < 30 buy, > 70 sell, exit at 50
  - `momentum_breakout.py` — Donchian(20) breakout + ATR(14) filter, exit on 10-bar low or ATR trail

  Plus seed a **`manual` strategy row** = the user's own portfolio, so manual and bot trading share
  one accounting model and the leaderboard compares you against the bots.

- [ ] **35. Create `backend/engine/runner.py`** — `StrategyRunner.run_all()` (the 15s job).
  **Evaluates on closed 1m bars only, never intra-bar.** Persists `signals` rows only when
  `action != HOLD`.

- [ ] **36. Create `backend/scheduler.py`** (extracted from `bot.py:start_bot`) — register
  `engine_tick` 1s, `strategy_tick` 15s, `candle_flush` 5s, `equity_snapshot` 30s, `prune` 1h.
  Set `max_instances=1`, `coalesce=True`, and a `misfire_grace_time` on **every** job.

- [ ] **37. Delete `backend/bot.py`.**

**✅ Phase 2 gate**
```bash
sqlite3 backend/crypto.db "select strategy_id,symbol,quantity,avg_entry_price from positions"
sqlite3 backend/crypto.db "select * from fills order by ts desc limit 5"   # real fees + realized P&L
```
Property test proves `equity == cash + realized + unrealized` at every step.

---

## Phase 3 — WebSocket API + REST v2

**Effort: M · Leaves the app: live ticks/orders/fills/equity streaming over `/ws`**

- [ ] **38. Create `backend/ws/hub.py`** — `Connection(id, ws, topics, queue=asyncio.Queue(maxsize=256), dropped)`
  and `Hub` with `connect/disconnect/subscribe/unsubscribe/publish/_writer`.
  - **Backpressure:** envelopes carry `coalesce: bool`. On overflow, evict the oldest *coalescable*
    message (ticks, candles, equity). If none can be evicted, close with `1013 Try Again Later`.
    **Order, fill, and halt messages are never dropped.**

- [ ] **39. Create `backend/ws/protocol.py`** — envelope
  `{"v":1,"type":...,"topic":...,"ts":"ISO8601Z","seq":<per-conn monotonic>,"data":{...}}`.
  `seq` lets the client detect drops.

- [ ] **40. Add `@app.websocket("/ws")` in `backend/api/ws_routes.py`**
  Topics: `ticks` · `candles:{SYM}:{INT}` · `orders` · `fills[:{key}]` · `positions:{key}` ·
  `equity` · `signals` · `feed` · `system`.
  Client ops: `{"op":"subscribe"|"unsubscribe","topics":[...]}`, `{"op":"ping"}`. Heartbeat every 15s.
  On subscribe, send only the current in-progress candle + last tick —
  **bulk history goes over REST, deltas over WS.**

- [ ] **41. Write the exact payloads into `docs/WS_PROTOCOL.md`** — this is the frontend's contract,
  and it's what unblocks Phase 4 running in parallel.
  ```jsonc
  // tick — batched at 4 Hz, short keys (highest-volume message)
  {"type":"tick","topic":"ticks","data":{"ticks":[
    {"s":"BTC","p":65172.63,"b":65172.63,"a":65172.64,"chg24h":0.283,
     "v24h":2927.08,"t":1786311919442,"src":"coinbase"}]}}

  // candle — t in SECONDS (lightweight-charts UTCTimestamp), strictly ascending, deduped
  {"type":"candle","topic":"candles:BTC:1m","data":{"symbol":"BTC","interval":"1m",
    "t":1786311900,"o":65160.0,"h":65198.99,"l":65140.15,"c":65184.53,"v":5.49,"closed":false}}

  {"type":"order","topic":"orders","data":{"id":42,"client_order_id":"…","strategy":"sma_cross",
    "symbol":"ETH","side":"BUY","order_type":"MARKET","quantity":1.2,"status":"FILLED",
    "avg_fill_price":1924.83,"reason":"sma_cross:golden_cross"}}

  {"type":"fill","topic":"fills","data":{"id":88,"order_id":42,"strategy":"sma_cross","symbol":"ETH",
    "side":"BUY","quantity":1.2,"price":1924.83,"fee":2.31,"realized_pnl":0.0,"liquidity":"TAKER"}}

  {"type":"position","topic":"positions:sma_cross","data":{"strategy":"sma_cross","symbol":"ETH",
    "quantity":1.2,"avg_entry_price":1926.75,"mark_price":1930.10,"market_value":2316.12,
    "unrealized_pnl":4.02,"unrealized_pnl_pct":0.174,"stop_loss_price":1888.2,
    "take_profit_price":2003.8}}

  {"type":"equity","topic":"equity","data":{"snapshots":[{"strategy":"sma_cross","ts":1786311930,
    "equity":100412.55,"cash":81234.10,"position_value":19178.45,"realized_pnl":301.22,
    "unrealized_pnl":111.33,"drawdown_pct":0.42,"return_pct":0.41}]}}

  {"type":"signal","topic":"signals","data":{"strategy":"rsi_mr","symbol":"SOL","action":"BUY",
    "strength":0.72,"price":142.15,"indicators":{"rsi":27.4}}}

  {"type":"feed","topic":"feed","data":{"status":"CONNECTED","provider":"coinbase","mode":"LIVE",
    "last_tick_age_ms":180,"reconnects":0,"degraded_from":null}}

  {"type":"heartbeat","topic":"system","data":{"server_time":"…","clients":3,"uptime_s":12345}}
  {"type":"error","topic":"system","data":{"code":"UNKNOWN_TOPIC","message":"…"}}
  ```

- [ ] **42. Split `main.py` into `backend/api/` routers** — `market.py`, `trading.py`,
  `strategies.py`, `system.py`, `ws_routes.py`. `main.py` shrinks to app construction + lifespan
  + `include_router`. Pydantic schemas move to `backend/schemas.py`.

- [ ] **43. Add the REST v2 endpoints** (hydration only — deltas come over WS)
  `GET /health` (extended with feed + db status) · `/assets` · `/market/summary` ·
  `/market/candles?symbol&interval&limit&before` · `/market/ticks?symbol&limit` · `/strategies` ·
  `/strategies/{key}` · `/strategies/{key}/metrics` · `/strategies/{key}/equity` ·
  `POST /strategies/{key}/{enable|disable|resume|reset}` · `/portfolio?strategy=` ·
  `/positions?strategy=` · `/orders?strategy&status&limit&offset` ·
  `POST /orders` (idempotent on `client_order_id`) · `DELETE /orders/{client_order_id}` ·
  `/fills?strategy&symbol&limit` · `/signals?strategy&symbol&limit` · `/feed/status`

- [ ] **44. Fix the symbol regex** — in `schemas.py`, replace every `pattern="^[A-Z]{3}$"` with
  `Field(pattern=r"^[A-Z0-9]{2,10}$")` plus a `field_validator` checking membership in `SYMBOLS`.
  Return a 422 naming the valid set.
  > Today **AVAX and DOGE both 422** on `POST /trade`. Also note `PortfolioItem.symbol`'s
  > `^[A-Z]{3}$|USD` alternative is un-anchored, so it matches any string *containing* "USD".

- [ ] **45. Add the `/ws` proxy to `frontend/vite.config.ts`** so dev and prod share one relative URL
  ```ts
  proxy: {
    '/api': { target:'http://localhost:8000', changeOrigin:true, rewrite: p => p.replace(/^\/api/,'') },
    '/ws':  { target:'ws://localhost:8000', ws:true }
  }
  ```

- [ ] **46. Delete the Phase-1 REST shims and `backend/config.py`**
  ⚠️ **Do this only after Phase 5 ships** — the shims are what keep the old UI usable during P1–P4.

**✅ Phase 3 gate**
```bash
npx wscat -c ws://localhost:8000/ws
> {"op":"subscribe","topics":["ticks","fills"]}
```
→ live envelopes with strictly ascending `seq`.

---

## Phase 4 — Frontend foundation

**Effort: M · Can run in parallel with Phase 3 once `docs/WS_PROTOCOL.md` exists**
**Leaves the app: dark terminal shell, live ticker strip, all data over WS**

- [ ] **47. Install Tailwind v4** — `npm i -D tailwindcss@^4.3.3 @tailwindcss/vite@^4.3.3`
  (peer allows Vite `^5.2.0` — **no Vite upgrade needed**)

- [ ] **48. Wire the plugin** — `vite.config.ts`: `import tailwindcss from '@tailwindcss/vite'`;
  `plugins: [react(), tailwindcss()]`.
  > **v4 is CSS-first: no `tailwind.config.js`, no PostCSS config, automatic content detection.**
  > Do not follow v3 tutorials.

- [ ] **49. Rewrite `frontend/src/index.css`** (currently 30 lines with zero classes)
  ```css
  @import "tailwindcss";
  @theme {
    --color-bg:#080b12; --color-surface:#0e131c; --color-surface-2:#151c28;
    --color-border:#1e2735; --color-text:#e6edf7; --color-muted:#7d8da6;
    --color-up:#16c784;   --color-up-soft:#16c78422;
    --color-down:#ea3943; --color-down-soft:#ea394322;
    --color-accent:#4c8dff; --color-warn:#f0b90b;
    --font-mono:"JetBrains Mono","SF Mono",ui-monospace,monospace;
    --radius-panel:10px;
  }
  @utility tabular { font-variant-numeric: tabular-nums; }
  @keyframes flash-up   { from { background: var(--color-up-soft);   } to { background: transparent; } }
  @keyframes flash-down { from { background: var(--color-down-soft); } to { background: transparent; } }
  ```
  > Monospace + `tabular-nums` on **every** number so prices don't jitter horizontally as digits
  > change. This one detail is most of what makes it read as a terminal.

- [ ] **50. Create `frontend/src/api/ws.ts`** — `WSClient` class
  - One app-level connection to `ws://${location.host}/ws`
  - Topic set with automatic re-subscribe on reconnect
  - Exponential backoff 500ms → 15s with jitter; `seq` gap detection
  - **rAF-coalesced apply buffer** so incoming tick batches update the store at most once per frame

- [ ] **51. Create `frontend/src/api/endpoints.ts`** (typed REST fns) and move the existing
  `src/api.ts` to `src/api/client.ts` — **it's small and correct, keep it as-is.**

- [ ] **52. Create `frontend/src/types/{market,trading,ws}.ts`** — TS mirrors of the envelope schemas
  from `docs/WS_PROTOCOL.md`.

- [ ] **53. Split `src/store.ts` into `src/store/`** — `marketSlice.ts`, `portfolioSlice.ts`,
  `strategySlice.ts`, `ordersSlice.ts`, `uiSlice.ts`, `selectors.ts`, `index.ts`
  - **Selector discipline is the load-bearing perf fix.** Today all four components do
    `const { ... } = useStore()`, subscribing to the *entire* store — every tick re-renders every
    mounted subtree. Ban whole-store destructuring; use narrow selectors + `useShallow`
    from `zustand/react/shallow`.
  - High-frequency reads bypass React: a `usePrice(symbol)` hook on `useSyncExternalStore`
    + `useStore.subscribe`, so a tick re-renders exactly one cell.
  - **Hydration composes with deltas by merge-on-key, never replace** — orders/fills by `id`,
    candles by `open_time`, positions by `(strategy, symbol)`. An in-flight WS delta must not be
    clobbered by a slower REST response.
  - Bounded collections: fills ≤ 200, ticks ≤ 300/symbol, candles ≤ 1000/(symbol, interval)
  - Per-collection `hydratedAt` drives skeletons — **fixes the current "No price data" flash**
    on first paint (today `loading` is dead on `PriceTable`/`Portfolio` because only `fetchAll` sets it)

- [ ] **54. Create `frontend/src/lib/format.ts`** — `fmtUsd`, `fmtPct`, `fmtQty`, `fmtCompact`,
  `fmtTime`, `fmtDuration`, `signClass`. **Every one returns `'—'` for `null`/`undefined`/`NaN`/`Infinity`.**
  Then add an eslint `no-restricted-syntax` rule banning `.toFixed(` in `src/components/**`.
  > Today unguarded `.toFixed()` on network data with no error boundary means **one null price
  > white-screens the entire app.** The rule stops the crash class coming back.

- [ ] **55. Create `frontend/src/components/common/`** — `ErrorBoundary.tsx` (class component),
  `Panel.tsx` (wraps children in one, so a bad panel shows "Panel error" instead of killing the
  terminal), `Skeleton.tsx`, `Toast.tsx`, `Pill.tsx`, `EmptyState.tsx`.

- [ ] **56. Create the shell** — `components/layout/{AppShell,TopBar,NavTabs,TickerStrip,ConnectionPill}.tsx`.
  `TopBar` shows a scrolling ticker strip and a live pill:
  `LIVE ● coinbase` / `DEGRADED ● binance` / `SIM ● synthetic`, driven by the `feed` topic.

- [ ] **57. Create `frontend/eslint.config.js`** (flat config) —
  `eslint@^9.39` + `typescript-eslint@^8.66` + `eslint-plugin-react-hooks@^7` + `globals@^17`.
  Change the lint script to `eslint .`
  > `npm run lint` **currently fails outright** — there is no eslint config file, and the
  > `--ext` flag is flat-config-incompatible.

**✅ Phase 4 gate:** shell renders, ticker strip animates, connection pill shows `LIVE ● coinbase`,
`npm run lint` passes.

---

## Phase 5 — The terminal dashboard

**Effort: L · This is the demo**

- [ ] **58. Install `lightweight-charts@^5.2.0`** — and nothing else
  > Canvas-based, so 500 candles updating at 4 Hz never touch React reconciliation;
  > `series.update()` is O(1); built-in crosshair/autoscale; multi-pane in v5 for volume and RSI;
  > ~45 KB gzip. Recharts re-renders SVG on every tick and would visibly stutter.
  >
  > **Also use it for the equity curves** (one `LineSeries` per strategy) — same wrapper, zero extra dep.
  >
  > **Explicitly do NOT add Recharts.** The donut (`stroke-dasharray` on a circle) and the bar chart
  > (`<rect>`s) are ~40 lines each in `components/viz/`; sparklines are a 25-line SVG polyline.

- [ ] **59. Create `components/market/CandleChart.tsx`**
  - **v5 API is `chart.addSeries(CandlestickSeries, opts, paneIndex)`** — `addCandlestickSeries()`
    is **gone**. Imports: `createChart, CandlestickSeries, HistogramSeries, LineSeries, createSeriesMarkers`
  - Two traps: **React StrictMode double-invokes effects in dev** — guard `createChart`/`chart.remove()`;
    and attach a `ResizeObserver` for container resize

- [ ] **60. Build `pages/TerminalPage.tsx`** — 12-column grid
  - **Row 1 · KPI strip** (4 × `col-span-3`): Total Equity (all strategies, with sparkline) ·
    Day P&L $/% · Open Positions + total exposure · Leading Strategy today
  - **Row 2** · `col-span-2` **Watchlist** (8 symbols: last price with tick-flash, 24h %, sparkline;
    click selects) · `col-span-7` **Chart panel** (candles + volume sub-pane, interval switcher
    1m/5m/15m/1h, SMA/Donchian overlays, RSI sub-pane, and **buy/sell markers from real fills**
    via `createSeriesMarkers` — *this is the money shot*) · `col-span-3` **Order ticket**
    (Market/Limit, BUY/SELL, qty or notional with 25/50/75/100% buttons, live estimated cost
    including modelled fee + slippage) over a compact manual **Positions** table
  - **Row 3** · `col-span-6` **Equity curves**, one line per strategy normalised to % return,
    legend with live values · `col-span-6` **Strategy leaderboard**: equity, return %, realized,
    unrealized, win rate, trades, max DD, status pill, enable/disable toggle, reset
  - **Row 4** · `col-span-8` **Live tape** — merged fills + signals + feed events, newest first,
    colour-coded, capped at 200 · `col-span-4` **Allocation donut** (cash vs per-symbol) +
    **drawdown gauge** showing distance to the kill-switch

- [ ] **61. Derive 5m/15m/1h client-side** by bucketing 1m candles — no extra tables, no extra endpoints.

**✅ Phase 5 gate:** candles update live · fill markers appear on the chart at the fill price ·
equity curves diverge across strategies · leaderboard reorders as bots perform.

---

## Phase 6 — Depth pages

**Effort: M**

- [ ] **62. `pages/StrategyDetailPage.tsx`** (`/strategies/:key`) — params, that strategy's equity
  curve, positions, fills, metrics grid, signal history, chart filtered to its markers
- [ ] **63. `pages/OrdersPage.tsx`** — full blotter, strategy/symbol/status/side filters,
  cancel on working limits
- [ ] **64. `pages/JournalPage.tsx`** — closed-trade journal (entry/exit, hold time, P&L, R-multiple)
  + P&L-by-symbol bar chart (hand-rolled SVG)
- [ ] **65. `pages/SettingsPage.tsx`** — feed status + manual failover trigger, risk parameters,
  density toggle, reset-all-portfolios behind a confirm
- [ ] **66. Delete the four legacy components** —
  `frontend/src/components/{Dashboard,PriceTable,Portfolio,TradeForm}.tsx`

---

## Phase 7 — Tests, docs, polish

**Effort: M**

- [ ] **67. Rewrite `backend/conftest.py`** — the in-memory StaticPool approach works, **keep it**;
  add `settings_override`, `market`, `engine`, and `client` fixtures.

- [ ] **68. Backend tests**
  - `test_feeds_parsing.py` — **inline the real captured payloads from steps 16–17** and assert the
    parsed `Tick`. No network.
  - `test_feed_manager.py` — `FakeFeed`s that raise/stall on command; assert the backoff schedule
    (monkeypatch `asyncio.sleep` to record delays), failover order, staleness-watchdog trip,
    failback promotion
  - `test_candles.py` — bucket boundaries (`:59.999` vs `:00.000`), OHLC correctness,
    rollover emits exactly once, upsert idempotency
  - `test_paper_broker.py` — deterministic fills from fixed bid/ask; slippage and fee math;
    limit trigger conditions; **every** rejection reason
  - `test_portfolio_accounting.py` — **property test**: random buy/sell sequences, assert
    `equity == starting_cash + realized + unrealized` to 1e-6 at every step, cash never negative,
    cost basis matches a reference implementation
  - `test_risk.py` — sizing, max positions, SL/TP triggers, drawdown kill-switch flattens and halts
  - `test_indicators.py` / `test_strategies.py` — known-value reference vectors; hand-built candle
    series producing an exact `Decision`
  - `test_ws.py` — `TestClient.websocket_connect("/ws?topics=ticks")`: envelope shape,
    subscribe/unsubscribe, heartbeat, unknown-topic error, overflow drop behaviour
  - Rework `test_integration.py` — synthetic tick → signal → order → fill → position → snapshot
    → REST → WS

- [ ] **69. Frontend tests** —
  `npm i -D vitest@^3.2.7 @vitest/coverage-v8@^3.2.7 jsdom@^26 @testing-library/react@^16.3 @testing-library/jest-dom@^6 @testing-library/user-event@^14`
  > **Pin vitest 3, not 4** — v4's peer requires Vite ≥ 6, and we're on Vite 5.

  Add `test: { environment:'jsdom', setupFiles:'./src/test/setup.ts', globals:true }` to `vite.config.ts`.
  Cover: `lib/format` (null/NaN never throws), `store/selectors`, `api/ws`
  (mock WebSocket → backoff, reconnect, dispatch), `Watchlist`, `OrderTicket`, `ErrorBoundary`.

- [ ] **70. Rewrite `CLAUDE.md` from scratch** — new architecture, **the "event loop never touches
  the DB" invariant**, the Python-3.9 constraint table, the table reference, the WS topic table,
  commands.
  > It is stale in ~10 specific ways today: says 8 endpoints (there are 9), says CORS is one origin,
  > says Zustand is unused, omits `TradeForm`/`api.ts`/`store.ts`/`test_integration.py`/`/health`,
  > and lists three already-fixed items under "Future Work".

- [ ] **71. Rewrite `README.md`** — remove its **three false claims**: that the DB resets on each
  start (it persists), that GitHub Actions CI runs on every push (there is no `.github/`), and that
  deps are pinned + `safety`-checked (they're `>=` floors). Also drop the "Vitest for frontend
  components" claim until step 69 lands. Add a screenshot section and a prominent disclaimer:
  **paper trading, real market data, no broker connected, not financial advice.**

- [ ] **72. Write `docs/ARCHITECTURE.md`** (the concurrency diagram) — `docs/WS_PROTOCOL.md`
  already exists from step 41.

- [ ] **73. Fold `QUICKSTART.md` into `README.md`; delete `QUICKSTART.md` and `FIXES_SUMMARY.md`**
  (a historical churn log with no forward value). Safe only because Phase 0 committed them.

**✅ Phase 7 gate:** `pytest -q` green · `npm run test` green · `npm run build` clean.

---

## Final acceptance

Start both servers and leave them running ~15 minutes:

- [ ] Real prices tick continuously across all 8 symbols
- [ ] At least one strategy opens a position
- [ ] The chart shows a buy marker at the actual fill price
- [ ] The equity curve moves off the flat line
- [ ] The leaderboard shows divergent returns between strategies
- [ ] Unplugging the network degrades to `SIM` without a crash, and recovers on reconnect

---

## Deliberately cut as over-engineering

Alembic (version-gated drop-and-recreate suffices for a single-user app) · Redis/Celery
(single process) · L2 order-book subscription (10× message volume, no payoff at top-of-book) ·
partial fills and queue modelling · shorting/margin/leverage · separate tables per candle interval
(derive from 1m) · Recharts (two hand-rolled SVGs instead) · numpy/pandas for indicators ·
a `feed_events` table · auth/users · Docker + CI (delete the README's false CI claim rather than
making it true) · a backtesting harness — *a whole second product; noted as future work*

## Known risks

| Risk | Mitigation |
| --- | --- |
| Python 3.9 vs the `>=3.12` claim — silent import crash | Step 6 + the constraint table at the top |
| SQLite `database is locked` (3 writer threads) | WAL + `busy_timeout=5000` — step 14, non-negotiable |
| Backfill rate-limit / IP-ban under `--reload` | Skip if newest candle < 2 min old; 250 ms stagger — step 19 |
| WebSocket open but silent | Staleness watchdog, not connection state — step 20 |
| Frontend re-render storms (8 symbols × 4 Hz) | Selectors + `useSyncExternalStore` + imperative charts — step 53 |
| Strategies churning on 1m bars lose to fees | Closed bars only, 15s cadence, 3-bar cooldown — steps 29, 35 |
| `crypto.db` gets dropped | Synthetic data only; the reset logs loudly — step 14 |
| WS has no auth | Fine on localhost; documented as a prod gap |
