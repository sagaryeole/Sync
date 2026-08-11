# Crypto Trade App

A lightweight paper-trading terminal being rebuilt from a mock-data demo into a live one. It pulls real market data from Coinbase/Binance (with a synthetic fallback) and trades it with virtual cash. No broker account is connected — everything is simulated.

> **Disclaimer:** This is a paper-trading simulator for educational purposes only. It uses real market data but virtual cash. Nothing here is financial advice, and no real money is ever at risk.

> **Status:** mid-rewrite, tracked in [`TODO.md`](TODO.md). Phase 0 (safety net/tooling) and Phase 1 (live feeds — Coinbase/Binance WebSocket with automatic failover to synthetic data) are complete and gate-verified. Phase 2's paper-trading engine (`backend/engine/`, `backend/strategies/`) is written but not yet wired into the running app — the live API still trades through the legacy moving-average bot in `backend/bot.py`. There is no WebSocket API for clients yet (planned for Phase 3); the frontend polls REST.

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
- **Bot logic (current)** – A single moving-average crossover bot (`backend/bot.py`) trades on a fixed interval via APScheduler; this is a legacy shim slated for removal once the engine below is wired in.
- **Bot logic (built, not yet wired in)** – `backend/engine/` (paper broker, risk manager, portfolio accounting) and `backend/strategies/` (SMA crossover, RSI reversion, momentum breakout, plus indicators) implement a multi-strategy paper-trading engine with SL/TP, position sizing, and a max-drawdown kill-switch. Not yet connected to the scheduler or REST API — see `TODO.md` Phase 2.

## Project Structure

```
CryptoTradeApp/
├── backend/
│   ├── main.py                 # FastAPI app & routes
│   ├── bot.py                  # Legacy bot compatibility shim
│   ├── config.py               # Back-compat config shim
│   ├── settings.py             # Pydantic-settings config
│   ├── models.py               # SQLAlchemy ORM models
│   ├── database.py             # DB connection & init
│   ├── requirements.txt         # Python dependencies
│   ├── feeds/                  # Market data feeds (Coinbase, Binance, synthetic)
│   ├── engine/                 # Paper trading engine, broker, risk, metrics
│   ├── strategies/             # Trading strategies
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
