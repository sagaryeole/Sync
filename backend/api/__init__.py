"""FastAPI API routers (Phase 3, step 42).

Routers are split by domain:
  - market.py: /assets, /market/* (prices, candles, ticks, summary)
  - trading.py: /portfolio, /positions, /orders, /fills, /trade (legacy shim)
  - strategies.py: /strategies/* (list, detail, metrics, equity, enable/disable)
  - system.py: /health, /feed/status, /ws/token
  - ws_routes.py: /ws WebSocket endpoint
"""
