# Crypto Trade App

A lightweight paper-trading terminal being rebuilt from a mock-data demo into a live one. It pulls real market data from Coinbase/Binance (with a synthetic fallback) and trades it with virtual cash. No broker account is connected — everything is simulated.

> **Disclaimer:** This is a paper-trading simulator for educational purposes only. It uses real market data but virtual cash. Nothing here is financial advice, and no real money is ever at risk.

> **Status:** mid-rewrite, tracked in [`TODO.md`](TODO.md). Phase 0 (safety net/tooling), Phase 1 (live feeds — Coinbase/Binance WebSocket with automatic failover to synthetic data), and Phase 2 (multi-strategy paper-trading engine) are complete and gate-verified. Four strategies (`manual`, `sma_crossover`, `rsi_reversion`, `momentum_breakout`) each trade their own paper portfolio against live prices with real fees, slippage, SL/TP, position sizing, and a max-drawdown kill-switch. There is no WebSocket API for clients yet (planned for Phase 3); the frontend still polls the legacy REST shims, which now sit in front of the new engine rather than the old single-bot.

## Quick Start

### Prerequisites
- Python 3.9+
- Node.js 16+
- pip and npm

### Setup (one-time)

**Backend:**
```bash
cd backend
pip install -r requirements.txt
```

**Frontend:**
```bash
cd frontend
npm install
```

### Run both servers

**Terminal 1 — Backend (FastAPI):**
```bash
cd backend
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 — Frontend (Vite):**
```bash
cd frontend
npm run dev
```

Open `http://localhost:3355` in your browser.

### Run backend tests
```bash
cd backend
python3 -m pytest -q
```

## Architecture

- **Backend** – FastAPI (Python) exposes REST endpoints and ingests a live WebSocket price feed (Coinbase primary, Binance secondary, synthetic fallback) into an in-memory market state, backed by a SQLite database.
- **Frontend** – React (Vite + TypeScript) consumes the REST API via polling and displays live prices, portfolio, and trade history.
- **Data persistence** – SQLite via SQLAlchemy; data survives restarts.
- **Paper-trading engine** – `backend/engine/` (`PaperEngine`, `PaperBroker`, `RiskManager`, `PortfolioAccount`) runs one portfolio per strategy: MARKET/LIMIT/STOP order types, realistic fees + slippage, SL/TP, position sizing (risk 2% of equity per trade, capped at 20%), and a max-drawdown kill-switch (halts + flattens at 25% drawdown from peak).
- **Strategies** – `backend/strategies/` implements `sma_crossover`, `rsi_reversion`, and `momentum_breakout` (plus a `manual` strategy = your own trades), evaluated every 15s on closed 1-minute bars by `StrategyRunner`. `backend/scheduler.py` drives the engine (`engine_tick` 1s, `strategy_tick` 15s, `equity_snapshot` 30s, `prune` 1h) — this replaces the old single moving-average bot in `bot.py`, which has been deleted.
- **Known gap** – account state is warm-started from the last persisted snapshot on restart, not replayed deterministically from the `fills` log, so a crash between a fill and its DB commit can still diverge (tracked as H5 in `TODO.md`).

## Project Structure

```
CryptoTradeApp/
├── backend/
│   ├── main.py                 # FastAPI app & routes
│   ├── scheduler.py             # Engine background jobs (engine_tick, strategy_tick, ...)
│   ├── config.py               # Back-compat config shim
│   ├── settings.py             # Pydantic-settings config
│   ├── models.py               # SQLAlchemy ORM models
│   ├── database.py             # DB connection & init
│   ├── requirements.txt         # Python dependencies
│   ├── feeds/                  # Market data feeds (Coinbase, Binance, synthetic)
│   ├── engine/                 # Paper trading engine, broker, risk, metrics, runner
│   ├── strategies/             # Trading strategies (sma_crossover, rsi_reversion, momentum_breakout)
│   ├── tests/                  # Backend tests (pytest)
│   └── crypto.db               # SQLite database
├── frontend/
│   ├── package.json            # NPM dependencies
│   ├── vite.config.ts          # Vite config
│   ├── tsconfig.json           # TypeScript config
│   └── src/
│       ├── main.tsx            # React entry
│       ├── App.tsx             # Main app component
│       ├── api.ts              # HTTP client
│       ├── store.ts            # Zustand state
│       └── components/         # Dashboard, PriceTable, Portfolio, TradeForm
├── CLAUDE.md                   # Codebase documentation & conventions
└── TODO.md                     # Implementation roadmap
```

## Notes

- Dependencies use `>=` floor constraints in `requirements.txt` / `package.json`. They are not pinned to exact versions, and there is no `safety` or `pip-audit` step in the current workflow.
- There is no CI/CD pipeline configured. Tests are run locally.
- The backend defaults to `127.0.0.1`. Set `HOST=0.0.0.0` to expose it on the LAN (not recommended unless you understand the security implications).
