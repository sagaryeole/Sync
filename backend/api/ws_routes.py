"""WebSocket /ws endpoint (step 40).

Handles the full lifecycle of a WebSocket connection:
  1. Origin validation (H2 — CSWSH protection) BEFORE accept
  2. Connection registration with the Hub (H8 per-IP limit)
  3. Inbound message loop (subscribe/unsubscribe/ping)
  4. Outbound writer task (drains the connection queue to the WS)
  5. Heartbeat every 15s
  6. On subscribe, sends current state (last tick, open candle) —
     bulk history goes over REST, deltas over WS.
  7. Global async pump drains the thread-safe EVENT_BUS into the hub.

Topics:
  ticks · candles:{SYM}:{INT} · orders · fills[:{key}] · positions:{key} ·
  equity · signals · feed · system
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from starlette.websockets import WebSocketState

from ws.hub import HUB, Connection, WS_CLOSE_POLICY_VIOLATION
from ws.protocol import parse_client_message, validate_topic, make_envelope, Envelope
from engine.events import EVENT_BUS
from feeds.symbols import SYMBOLS
from settings import get_settings

logger = logging.getLogger("api.ws")

router = APIRouter()

HEARTBEAT_INTERVAL = 15.0  # seconds
MAX_MESSAGE_SIZE = 1024 * 1024  # 1 MB — H8 inbound cap
KNOWN_SYMBOLS: Set[str] = set(SYMBOLS.keys())

# H2: single-use WS connect tokens
_WS_TOKENS: Set[str] = set()
_TOKEN_TTL = 300  # 5 minutes

# Keep the pump running even when no WS clients are connected
_pump_running = False
_pump_task: Optional[asyncio.Task] = None


async def _event_bus_pump():
    """Drain the thread-safe EVENT_BUS into the hub forever.

    The EVENT_BUS is a queue.Queue (thread-safe) that engine/scheduler
    threads push events into. This async pump drains it and publishes
    to the hub, which fans out to subscribed WebSocket connections.
    """
    global _pump_running
    _pump_running = True
    logger.info("Event bus pump started")
    while _pump_running:
        try:
            event = EVENT_BUS.get_nowait()
        except Exception:
            await asyncio.sleep(0.01)
            continue

        topic = event.get("topic", "")
        event_type = event.get("type", "")
        data = event.get("data", {})

        envelope = make_envelope(
            msg_type=event_type,
            topic=topic,
            data=data,
        )
        await HUB.publish(envelope)


def _ensure_pump():
    """Start the event bus pump if it's not running."""
    global _pump_task
    if _pump_task is None or _pump_task.done():
        loop = asyncio.get_event_loop()
        _pump_task = loop.create_task(_event_bus_pump())


def _get_allowed_origins() -> Set[str]:
    """Get the set of allowed WebSocket origins from settings."""
    settings = get_settings()
    return set(settings.cors_origins)


def _validate_origin(origin: Optional[str]) -> bool:
    """H2: Validate the Origin header against the allowlist.

    Returns True if the origin is allowed, False otherwise.
    A missing origin is also rejected (non-browser clients should use
    the token path).
    """
    if not origin:
        return False
    allowed = _get_allowed_origins()
    return origin in allowed


async def _send_envelope(ws: WebSocket, conn: Connection, envelope: Envelope) -> bool:
    """Send an envelope over the WebSocket, assigning the per-connection seq.

    Returns True if sent, False on error (connection should close).
    """
    envelope.seq = conn.next_seq()
    try:
        await ws.send_text(envelope.to_json())
        return True
    except Exception as e:
        logger.debug("WS send failed for conn %s: %s", conn.id[:8], e)
        return False


async def _send_error(ws: WebSocket, conn: Connection, code: str, message: str) -> None:
    """Send an error envelope to a connection."""
    env = make_envelope("error", "system", {"code": code, "message": message})
    await _send_envelope(ws, conn, env)


async def _send_initial_state(ws: WebSocket, conn: Connection, topic: str) -> None:
    """On subscribe, send the current state for the topic.

    For ticks: send the latest tick for each symbol.
    For candles:{SYM}:{INT}: send the current in-progress candle.
    For feed: send current feed status.

    Bulk history goes over REST, not WS.
    """
    from engine.market_state import MARKET
    from main import feed_manager

    ttype = topic.split(":")[0]

    if ttype == "ticks":
        for sym in get_settings().symbols:
            tick = MARKET.last_tick(sym)
            if tick is not None:
                env = make_envelope("tick", "ticks", {
                    "ticks": [{
                        "s": sym,
                        "p": tick.price,
                        "b": tick.bid,
                        "a": tick.ask,
                        "t": int(tick.ts.timestamp() * 1000) if tick.ts else None,
                        "src": tick.source,
                    }],
                })
                await _send_envelope(ws, conn, env)

    elif ttype == "candles":
        parts = topic.split(":")
        if len(parts) == 3:
            symbol = parts[1]
            open_c = MARKET.open_candle(symbol)
            if open_c is not None:
                env = make_envelope("candle", topic, {
                    "symbol": symbol,
                    "interval": parts[2],
                    "t": int(open_c["open_time"].timestamp()) if open_c.get("open_time") else None,
                    "o": open_c["open"],
                    "h": open_c["high"],
                    "l": open_c["low"],
                    "c": open_c["close"],
                    "v": open_c["volume"],
                    "closed": False,
                })
                await _send_envelope(ws, conn, env)

    elif ttype == "feed":
        status = feed_manager.get_status()
        env = make_envelope("feed", "feed", {
            "status": status["status"],
            "provider": status["provider"],
            "mode": status["mode"],
            "last_tick_age_ms": status["last_tick_age_ms"],
            "reconnects": status["reconnects"],
        })
        await _send_envelope(ws, conn, env)


async def _writer_task(ws: WebSocket, conn: Connection) -> None:
    """Background task that drains the connection queue and sends to the WS.

    Runs concurrently with the inbound message reader. Exits when the
    connection is closed or the task is cancelled.
    """
    try:
        while not conn.closed:
            try:
                envelope = await asyncio.wait_for(conn.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if conn.closed:
                    break
                continue
            envelope.seq = conn.next_seq()
            try:
                await ws.send_text(envelope.to_json())
            except Exception as e:
                logger.debug("Writer send failed for conn %s: %s", conn.id[:8], e)
                conn.closed = True
                break
    except asyncio.CancelledError:
        pass


async def _heartbeat_task(ws: WebSocket, conn: Connection) -> None:
    """Background task that sends a heartbeat every 15 seconds."""
    try:
        while not conn.closed:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if conn.closed:
                break
            stats = HUB.get_stats()
            env = make_envelope("heartbeat", "system", {
                "server_time": datetime.now(timezone.utc).isoformat(),
                "clients": stats["connections"],
                "uptime_s": 0,
            })
            ok = await HUB.publish_to_connection(conn, env)
            if not ok:
                conn.closed = True
                break
    except asyncio.CancelledError:
        pass


@router.get("/ws/token")
def get_ws_token():
    token = secrets.token_urlsafe(32)
    _WS_TOKENS.add(token)
    if len(_WS_TOKENS) > 1000:
        _WS_TOKENS.pop()
    return {"token": token, "expires_in": _TOKEN_TTL}


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    topics: Optional[str] = Query(default=None),
    token: Optional[str] = Query(default=None),
) -> None:
    """Main WebSocket endpoint.

    Query params:
      topics: Comma-separated list of initial topics to subscribe to
              (e.g. /ws?topics=ticks,fills)

    The connection is rejected if:
      - The Origin header is not in the allowlist (H2)
      - The IP has exceeded the connection limit (H8)
    """
    # H2: Validate Origin BEFORE accepting
    origin = ws.headers.get("origin")
    if not _validate_origin(origin):
        logger.warning("WS rejected: invalid origin '%s'", origin)
        await ws.close(code=WS_CLOSE_POLICY_VIOLATION, reason="Invalid origin")
        return

    # H2: Validate connect token
    if token not in _WS_TOKENS:
        logger.warning("WS rejected: invalid token")
        await ws.close(code=WS_CLOSE_POLICY_VIOLATION, reason="Invalid token")
        return
    _WS_TOKENS.discard(token)

    # Get client IP
    client_ip = ws.client.host if ws.client else "unknown"

    # Parse initial topics from query param
    initial_topics: Set[str] = set()
    if topics:
        for t in topics.split(","):
            t = t.strip()
            if t:
                initial_topics.add(t)

    # Validate initial topics
    for topic in list(initial_topics):
        if not validate_topic(topic, KNOWN_SYMBOLS):
            initial_topics.discard(topic)

    # Register with the hub (enforces per-IP connection limit)
    conn = await HUB.connect(ws, ip=client_ip, initial_topics=initial_topics)
    if conn is None:
        await ws.close(code=WS_CLOSE_POLICY_VIOLATION, reason="Too many connections")
        return

    # Accept the WebSocket
    await ws.accept()

    # Start the event bus pump
    _ensure_pump()

    # Send initial state for subscribed topics
    for topic in list(conn.topics):
        await _send_initial_state(ws, conn, topic)

    # Start the writer and heartbeat tasks
    writer = asyncio.create_task(_writer_task(ws, conn))
    heartbeat = asyncio.create_task(_heartbeat_task(ws, conn))

    try:
        # Inbound message loop
        while not conn.closed:
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.debug("WS receive error for conn %s: %s", conn.id[:8], e)
                break

            if len(raw) > MAX_MESSAGE_SIZE:
                await _send_error(ws, conn, "MESSAGE_TOO_LARGE",
                                  f"Message exceeds {MAX_MESSAGE_SIZE} bytes")
                await ws.close(code=1009)
                break

            parsed = parse_client_message(raw)
            if parsed["error"]:
                await _send_error(ws, conn, "PARSE_ERROR", parsed["error"])
                continue

            op = parsed["op"]
            topics_list = parsed["topics"]

            if op == "ping":
                env = make_envelope("pong", "system", {})
                await _send_envelope(ws, conn, env)

            elif op == "sync":
                for topic in list(conn.topics):
                    await _send_initial_state(ws, conn, topic)

            elif op == "subscribe":
                valid = set()
                invalid = []
                for t in topics_list:
                    if validate_topic(t, KNOWN_SYMBOLS):
                        valid.add(t)
                    else:
                        invalid.append(t)

                if invalid:
                    await _send_error(ws, conn, "UNKNOWN_TOPIC",
                                       f"Invalid topics: {invalid}")

                if valid:
                    result = await HUB.subscribe(conn, valid)
                    if result["rejected"]:
                        await _send_error(ws, conn, "TOPIC_LIMIT",
                                           f"Topic limit exceeded for: {result['rejected']}")
                    # Send initial state for newly subscribed topics
                    for t in result["added"]:
                        await _send_initial_state(ws, conn, t)
                    # Confirm subscription
                    if result["added"]:
                        env = make_envelope("subscribed", "system", {
                            "topics": sorted(result["added"]),
                        })
                        await _send_envelope(ws, conn, env)

            elif op == "unsubscribe":
                removed = await HUB.unsubscribe(conn, set(topics_list))
                if removed:
                    env = make_envelope("unsubscribed", "system", {
                        "topics": sorted(removed),
                    })
                    await _send_envelope(ws, conn, env)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WS error for conn %s: %s", conn.id[:8], e)
    finally:
        conn.closed = True
        writer.cancel()
        heartbeat.cancel()
        await asyncio.gather(writer, heartbeat, return_exceptions=True)
        await HUB.disconnect(conn)
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.close()
        except Exception:
            pass
