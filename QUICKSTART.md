# Quick Start Guide

## Prerequisites
- Python 3.9+ (for backend)
- Node.js 16+ (for frontend)
- pip and npm already installed

## Setup (One-time)

### Backend Setup
```bash
cd backend
pip install -r requirements.txt
```

### Frontend Setup
```bash
cd frontend
npm install
```

---
in this 
## Running the App

### Option 1: Run Both Servers (Recommended)

**Terminal 1 - Backend API:**
```bash
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 - Frontend Dev Server:**
```bash
cd frontend
npm run dev
```

**Then open in browser:**
```
http://localhost:5173
```

---

### Option 2: Backend Only (for testing APIs)

```bash
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Access Swagger UI:**
```
http://localhost:8000/docs
```

**Test endpoints:**
```bash
# List assets
curl http://localhost:8000/assets

# Get prices
curl http://localhost:8000/prices

# Get portfolio
curl 'http://localhost:8000/portfolio?symbol=USD'

# Get bot signals
curl http://localhost:8000/bot/signals
```

---

## What Each Component Does

### Backend (FastAPI)
- **Port:** 8000
- **Entry:** `backend/main.py`
- **DB:** SQLite at `backend/crypto.db`
- **Bot:** Runs every 60 seconds, executes trades

### Frontend (React + Vite)
- **Port:** 5173
- **Entry:** `frontend/src/main.tsx`
- **Components:** Dashboard, PriceTable, Portfolio

### Bot Trading Logic
- **Strategy:** Simple Moving Average (MA) Crossover
- **Period:** 5-minute MA window
- **Signals:** BUY if price < 98% of MA, SELL if > 102% of MA
- **Trade Size:** $100 per BUY trade, all holdings on SELL

---

## Testing

### Run Backend Tests
```bash
cd backend
python3 -m pytest tests/test_bot.py -v
```

### Run Frontend Linter
```bash
cd frontend
npm run lint
```

---

## Troubleshooting

### "Port already in use" error
```bash
# Kill existing processes
pkill -f "uvicorn\|vite\|node"

# Then restart
```

### Dependencies not installing
```bash
# Backend
cd backend
pip install --upgrade pip
pip install -r requirements.txt

# Frontend
cd frontend
rm -rf node_modules package-lock.json
npm install
```

### Database issues
```bash
# Reset database
rm backend/crypto.db
# Restart backend - it will recreate on startup
```

### Can't connect frontend to backend
- Check backend is running on http://localhost:8000
- Check CORS settings in `backend/main.py` (should allow localhost:5173)
- Check browser console for errors

---

## Files Structure

```
CryptoTradeApp/
├── backend/
│   ├── main.py                 # FastAPI app & routes
│   ├── bot.py                  # Trading bot logic
│   ├── models.py               # SQLAlchemy ORM models
│   ├── database.py             # DB connection & init
│   ├── config.py               # Configuration
│   ├── requirements.txt         # Python dependencies
│   ├── tests/
│   │   ├── test_api.py         # API endpoint tests
│   │   └── test_bot.py         # Bot logic tests
│   └── crypto.db               # SQLite database
│
├── frontend/
│   ├── index.html              # HTML entry point
│   ├── package.json            # NPM dependencies
│   ├── vite.config.ts          # Vite config
│   ├── tsconfig.json           # TypeScript config
│   └── src/
│       ├── main.tsx            # React entry
│       ├── App.tsx             # Main app component
│       └── components/
│           ├── Dashboard.tsx   # Main dashboard
│           ├── PriceTable.tsx  # Price history
│           └── Portfolio.tsx   # Portfolio view
│
├── CLAUDE.md                   # Codebase documentation
├── FIXES_SUMMARY.md            # All bugs fixed
└── QUICKSTART.md               # This file
```

---

## Key Fixes Applied

1. ✅ Added missing imports to `bot.py`
2. ✅ Implemented 5 missing bot functions
3. ✅ Fixed SQLAlchemy Column definitions
4. ✅ Added Session export to `database.py`
5. ✅ Initialized bot scheduler in FastAPI startup
6. ✅ Fixed Decimal/float type conversions
7. ✅ Created pytest configuration & test isolation
8. ✅ Created `frontend/index.html`

See `FIXES_SUMMARY.md` for detailed information on each fix.

---

## Support

For detailed architecture information, see `CLAUDE.md`

For specific bug fixes applied, see `FIXES_SUMMARY.md`
