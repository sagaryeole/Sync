"""WebSocket hub and protocol for real-time streaming.

Phase 3 (steps 38-41): the /ws endpoint streams ticks, candles, orders,
fills, positions, equity, signals, and feed status to browser clients.
The hub is async-native (FastAPI/Starlette), while the engine and feed
push events through a thread-safe queue (engine.events.EVENT_BUS) that
a single async pump drains into the hub.
"""
