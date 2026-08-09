# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

This is a monorepo with independent backend (FastAPI) and frontend (React) directories. Each has its own package manager and dev server.

### Backend (Python/FastAPI)

```bash
# Install dependencies
cd backend && pip install -r requirements.txt

# Run the server (with hot reload)
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Run tests
cd backend && pytest

# Run a single test
cd backend && pytest tests/test_api.py::test_list_assets -v

# Format & lint
cd backend && black . && isort . && flake8
```

### Frontend (React/Vite)

```bash
# Install dependencies
cd frontend && npm install

# Run dev server
cd frontend && npm run dev

# Build for production
cd frontend && npm run build

# Lint
cd frontend && npm run lint
```

## Architecture

### Backend Architecture

**Core Components:**
- `main.py` – FastAPI app with 8 REST endpoints for assets, prices, portfolio, trades, and bot signals
- `bot.py` – Background scheduler loop running bot trades via **moving average crossover strategy**; imports `Portfolio` and `TradeLog` models but the actual execute_trade logic is in bot.py
- `models.py` – SQLAlchemy ORM: Asset, PriceTicker, Portfolio, TradeLog
- `database.py` – Session management and DB initialization (SQLite)
- `config.py` – Constants: assets (BTC, ETH, SOL), scheduler interval (60s), bot MA period (5 min), CORS/DB URLs

**Key Trade Logic Flow:**
1. Bot scheduler runs `run_bot_cycle()` every 60 seconds
2. `generate_mock_price()` adds a new price point using volatility-based random walk (no trend)
3. `get_signal()` computes SMA over 5 min window; returns "BUY" if price < 98% of MA, "SELL" if > 102% of MA
4. `execute_trade()` updates Portfolio (add/remove quantity, adjust USD balance) and logs to TradeLog
5. Bot only trades $100 per cycle (or all holdings on SELL) if signal and balance conditions met

**CORS:** Hardcoded to `http://localhost:5173` (frontend dev server)

### Frontend Architecture

**React + Vite + TypeScript:**
- Entry: `src/main.tsx` → `src/App.tsx`
- Components in `src/components/`:
  - `Dashboard.tsx` – Top-level layout with nav, displays current prices and portfolio value
  - `PriceTable.tsx` – Historical price data; fetches `/prices` endpoint
  - `Portfolio.tsx` – User holdings (quantity, balance, cost basis); fetches `/portfolio?symbol=<SYMBOL>` for each asset
- State: Zustand store (not yet fully integrated in existing tests/components; see imports in test expectations)
- HTTP: axios to `http://localhost:8000` (backend)
- Routes: React Router (installed but basic setup in App.tsx)

### Data Model

**SQLite Tables:**
- `assets` – Static: BTC, ETH, SOL (id, symbol, name)
- `prices` – Time series: symbol, price, timestamp (indexed on symbol)
- `portfolios` – User holdings per asset: symbol (PK), balance (USD), quantity (coins), cost_basis
- `trades` – Log: id, type (BUY/SELL), symbol, quantity, price, timestamp

## Key Design Notes

### Bot Strategy
- **Simple MA Crossover:** Current price vs. 5-min SMA; no ML or complex features
- **Budget:** $100 USD per BUY trade (capped by balance); full holdings on SELL
- **Volatility:** BTC ±1%, ETH ±1.5%, SOL ±2.5% per cycle; controlled in `generate_mock_price()`
- **DB Reset:** SQLite in-memory/local file reset on app startup; no persistence across restarts

### API Design
- Request validation via Pydantic (symbol regex patterns, quantity >= 0)
- Responses are mostly Pydantic models mapped from SQLAlchemy ORM
- `/trade` endpoint refreshes prices and re-runs bot logic in-process (not asynchronous)
- `/bot/signals` returns live signal for each asset (useful for testing/debugging)

### Backend Imports Matter
- `from bot import run_bot_cycle, get_signal, generate_mock_price` – These three are key exports
- `from database import get_session, init_db, close_db` – DB lifecycle
- `from models import Asset, PriceTicker, Portfolio, TradeLog` – ORM models
- Tests mock/patch the Session and use in-memory tables

## Testing

### Backend Tests
- **Framework:** pytest (run from `backend/` directory)
- **Setup:** `test_db` fixture creates fresh in-memory DB per test, cleans up after
- **Coverage:** `test_api.py` (8 endpoint tests), `test_bot.py` (4 bot logic tests)
- **Patterns:** Use `Session()` for DB access, mock PriceTicker/Portfolio with plain objects where needed
- **Note:** Tests may use deprecated or mocked `should_buy()` function—verify actual function name in bot.py is `get_signal()`

### Frontend Tests
- No Jest/Vitest tests yet; linter is eslint (run `npm run lint`)
- Components are simple; prop-drilling from App → Dashboard → Portfolio/PriceTable
- No mocking of axios calls in existing tests; real HTTP on localhost:8000

## Common Tasks

### Add a New Endpoint
1. Define Pydantic request/response models in `main.py` or a `schemas.py` if models grow
2. Implement route with `@app.get()` or `@app.post()`; dependency-inject `db: Session`
3. Add test in `tests/test_api.py`
4. If it triggers bot logic, call `run_bot_cycle(db)` or specific bot functions

### Modify Bot Strategy
- Edit `get_signal()` in `bot.py` to change buy/sell thresholds (currently ±2%)
- Edit `run_bot_cycle()` to change trade amount ($100) or conditions
- Adjust `BOT_PERIOD` in `config.py` for MA window size (currently 5 min)
- Run `pytest tests/test_bot.py` to verify logic

### Add a Frontend Component
1. Create `.tsx` file in `src/components/`
2. Use axios to call backend endpoints (base URL: `http://localhost:8000`)
3. Wire into App.tsx route or Dashboard layout
4. Run `npm run lint` to check TypeScript and ESLint

## Dev Workflow

1. **Terminal 1 (Backend):**
   ```bash
   cd backend
   pip install -r requirements.txt  # one-time
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Terminal 2 (Frontend):**
   ```bash
   cd frontend
   npm install  # one-time
   npm run dev
   ```

3. **Browser:** Open `http://localhost:5173` (Vite dev server)

4. **Testing:** In a third terminal, run:
   ```bash
   cd backend && pytest -v
   cd frontend && npm run lint
   ```

## Dependencies

**Backend:**
- FastAPI 0.111+: Web framework
- Uvicorn 0.30+: ASGI server
- SQLAlchemy 2.0+: ORM
- Pydantic 2.8+: Request validation
- APScheduler 3.10+: Background scheduler for bot cycle

**Frontend:**
- React 18.3+: UI library
- Vite 5.2+: Build tool
- TypeScript 5.4+: Language
- Axios 1.7+: HTTP client
- React Router 6.24+: Routing
- Zustand 4.5+: State management (installed, may not be fully used)
- ESLint 8.57+: Linting

## Environment & Defaults

- **Backend Port:** 8000 (hardcoded in uvicorn commands)
- **Frontend Port:** 5173 (Vite default)
- **DB:** SQLite at `backend/crypto.db` (local file)
- **Bot Scheduler:** Runs every 60 seconds (`config.SCHEDULER_INTERVAL`)
- **CORS Origin:** Hardcoded to `http://localhost:5173` in main.py middleware

## Notes for Future Work

- **Scheduler cleanup:** The bot starts a background APScheduler on app startup but is not explicitly stopped on shutdown; consider adding proper lifecycle management
- **DB queries:** Some queries manually order by timestamp desc and limit; consider adding query helpers to reduce repetition
- **Cost basis logic:** Portfolio cost_basis calculation in `execute_trade()` SELL branch may have a bug (redundant recalculation); verify and fix
- **Frontend state:** Zustand store is installed but components use props; migrate to centralized state if app grows
- **Error handling:** Frontend components don't handle HTTP errors gracefully (no try/catch or error boundaries)
- **Tests:** Some test imports reference functions that may not exist (e.g., `should_buy` vs `get_signal`); audit test suite
