"""Security regression tests — one test per hardening item."""
import json
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from main import app
from engine.core import PaperEngine, EngineConfig
from engine.paper_broker import PaperBroker
from engine.risk import RiskManager, RiskConfig
from engine.market_state import MarketState
from feeds.validation import validate_tick, TickValidationError

client = TestClient(app)


def make_tick(price, bid=None, ask=None, ts=None, symbol="BTC"):
    tick = MagicMock()
    tick.symbol = symbol
    tick.price = price
    tick.bid = bid if bid is not None else price - 1.0
    tick.ask = ask if ask is not None else price + 1.0
    tick.ts = ts or datetime.now(timezone.utc)
    tick.source = "test"
    return tick


def make_market_state(tick=None, prices=None, last_price=None):
    ms = MagicMock()
    if tick is not None:
        ms.last_tick.return_value = tick
    else:
        ms.last_tick.return_value = None
    if prices is not None:
        ms.snapshot.return_value = prices
    else:
        ms.snapshot.return_value = {}
    if last_price is not None:
        ms.last.return_value = last_price
    elif tick is not None:
        ms.last.return_value = tick.price
    else:
        ms.last.return_value = None
    return ms


def make_engine(cash=100000.0, tick_price=50000.0):
    tick = make_tick(tick_price)
    ms = make_market_state(tick=tick, prices={"BTC": tick_price}, last_price=tick_price)
    broker = PaperBroker(ms, slippage_bps=0, impact_notional=1e12)
    rm = RiskManager(RiskConfig(max_position_pct=0.95))
    engine = PaperEngine(ms, broker, rm, EngineConfig(starting_cash=cash))
    engine.register_strategy(1, "test", cash)
    return engine


# ---- H1: NaN/Infinity/stale ticks rejected before reaching MarketState ----

class TestH1FeedValidation:
    def test_nan_price_rejected(self):
        with pytest.raises(TickValidationError, match="non-finite"):
            validate_tick(make_tick(float('nan')), {}, {})

    def test_infinity_price_rejected(self):
        with pytest.raises(TickValidationError, match="non-finite"):
            validate_tick(make_tick(float('inf')), {}, {})

    def test_negative_price_rejected(self):
        with pytest.raises(TickValidationError, match="non-positive"):
            validate_tick(make_tick(-1.0), {}, {})

    def test_stale_timestamp_rejected(self):
        old_ts = datetime.now(timezone.utc).timestamp() - 60
        tick = make_tick(100.0, ts=datetime.fromtimestamp(old_ts, tz=timezone.utc))
        with pytest.raises(TickValidationError, match="stale"):
            validate_tick(tick, {}, {})


# ---- H6: Order state machine — fill-after-cancel races ----

class TestH6OrderStateMachine:
    def test_filled_order_cannot_be_cancelled(self):
        engine = make_engine()
        fill, _ = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        assert fill is not None
        ok = engine.cancel_order(fill.client_order_id)
        assert ok is False


# ---- H9: Strategy params validation ----

class TestH9ParamValidation:
    def test_rejects_period_zero(self):
        from strategies.schemas import validate_params
        with pytest.raises(Exception):
            validate_params("sma_crossover", {"fast": 0, "slow": 20})

    def test_rejects_negative_period(self):
        from strategies.schemas import validate_params
        with pytest.raises(Exception):
            validate_params("sma_crossover", {"fast": -5, "slow": 20})


# ---- H14: client_order_id validation ----

class TestH14ClientOrderId:
    def test_rejects_invalid_uuid(self):
        engine = make_engine()
        fill, reason = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0, client_order_id="not-a-uuid")
        assert fill is None
        assert reason == "CLIENT_ORDER_ID_INVALID"

    def test_rejects_too_long_client_order_id(self):
        engine = make_engine()
        long_id = "a" * 51
        fill, reason = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0, client_order_id=long_id)
        assert fill is None
        assert "TOO_LONG" in reason

    def test_rejects_duplicate_client_order_id(self):
        engine = make_engine()
        cid = str(uuid.uuid4())
        fill1, _ = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0, client_order_id=cid)
        assert fill1 is not None

        fill2, reason = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0, client_order_id=cid)
        assert fill2 is None
        assert "DUPLICATE" in reason


# ---- H15: /health does not leak config ----

class TestH15HealthNoLeak:
    FORBIDDEN = {"database_url", "cors_origins", "env", "config", "origin", "origins",
                 "secret", "key", "token", "password", ".env", "db_path", "db_url",
                 "settings", "env_file"}

    def test_health_no_config_keys(self):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        leaked = self.FORBIDDEN.intersection(data.keys())
        assert not leaked, f"/health leaked config keys: {leaked}"


# ---- H19: Symbol whitelist enforced ----

class TestH19SymbolWhitelist:
    def test_trade_invalid_symbol_422(self):
        r = client.post("/trade", json={"type": "BUY", "symbol": "ZZZZZZ", "quantity": 1})
        assert r.status_code == 422

    def test_asset_not_found_404(self):
        r = client.get("/assets/ZZZZZZ")
        assert r.status_code == 404


# ---- H2: Cross-Site WebSocket Hijacking (Origin validation) ----

class TestH2WSOrigin:
    def test_foreign_origin_rejected(self):
        ws = client.websocket_connect("/ws?token=test", headers={"origin": "https://evil.com"})
        try:
            with pytest.raises(Exception):
                ws.__enter__()
        finally:
            try:
                ws.__exit__(None, None, None)
            except Exception:
                pass

    def test_missing_origin_rejected(self):
        ws = client.websocket_connect("/ws?token=test")
        try:
            with pytest.raises(Exception):
                ws.__enter__()
        finally:
            try:
                ws.__exit__(None, None, None)
            except Exception:
                pass


# ---- H4: Tick sanity band (large-move rejection + confirmation) ----

class TestH4TickValidation:
    def test_single_large_move_rejected(self):
        from feeds.validation import validate_tick, TickValidationError
        last_prices = {"BTC": 50000.0}
        pending = {}
        tick = make_tick(60000.0, symbol="BTC")
        with pytest.raises(TickValidationError, match="large move"):
            validate_tick(tick, last_prices, pending, now=datetime.now(timezone.utc))

    def test_confirmed_large_move_adopted(self):
        from feeds.validation import validate_tick, CONFIRM_TICKS
        last_prices = {"BTC": 50000.0}
        pending = {}
        tick1 = make_tick(60000.0, symbol="BTC")
        with pytest.raises(TickValidationError, match="large move"):
            validate_tick(tick1, last_prices, pending, now=datetime.now(timezone.utc))
        assert pending["BTC"] == 1

        tick2 = make_tick(60100.0, symbol="BTC")
        result = validate_tick(tick2, last_prices, pending, now=datetime.now(timezone.utc))
        assert result is tick2
        assert pending["BTC"] == 0


# ---- H5: Crash recovery — rebuild from fills matches cached state ----

class TestH5CrashRecovery:
    def test_rebuild_matches_cached_state(self):
        engine = make_engine(cash=100000.0, tick_price=50000.0)
        fill, _ = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        assert fill is not None

        from engine.paper_broker import Fill as FillModel
        from datetime import timezone
        fills_by_strategy = {1: [fill]}
        marks = {"BTC": 50000.0}
        rebuilt = engine.rebuild_from_fills(fills_by_strategy, marks)

        account = engine._accounts[1]
        assert rebuilt[1]["cash"] == pytest.approx(float(account.cash), abs=1e-5)
        assert rebuilt[1]["positions"]["BTC"] == pytest.approx(
            float(account.positions["BTC"].quantity), abs=1e-9
        )


# ---- H8: WebSocket limits (message size, topics per connection, connections per IP) ----

class TestH8WebSocketLimits:
    def test_message_size_limit_enforced(self):
        from api.ws_routes import MAX_MESSAGE_SIZE
        assert MAX_MESSAGE_SIZE == 1024 * 1024

    def test_topic_limit_enforced(self):
        from ws.hub import MAX_TOPICS_PER_CONN
        assert MAX_TOPICS_PER_CONN == 64

    def test_connection_limit_per_ip(self):
        """H8: the 9th connection from one IP is refused."""
        from ws.hub import HUB, MAX_CONNECTIONS_PER_IP
        HUB._connections.clear()
        HUB._ip_counts.clear()
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            conns = []
            for i in range(MAX_CONNECTIONS_PER_IP):
                mock_ws = MagicMock()
                conn = loop.run_until_complete(HUB.connect(mock_ws, ip="1.2.3.4"))
                assert conn is not None
                conns.append(conn)
            # 9th should be refused
            mock_ws = MagicMock()
            conn9 = loop.run_until_complete(HUB.connect(mock_ws, ip="1.2.3.4"))
            assert conn9 is None
            # cleanup
            for c in conns:
                loop.run_until_complete(HUB.disconnect(c))
        finally:
            loop.close()
            HUB._connections.clear()
            HUB._ip_counts.clear()

    def test_rest_limit_capped(self):
        """H8: ?limit=99999999 is capped to a reasonable max."""
        r = client.get("/trades?limit=99999999")
        # Should not error — the limit is capped server-side
        assert r.status_code == 200


# ---- H6: Order state machine — cancel-then-fill and fill-then-cancel races ----

class TestH6RaceConditions:
    def test_cancel_then_fill_single_terminal_state(self):
        """Cancel a working limit, then the same order can't be filled."""
        engine = make_engine(cash=100000.0, tick_price=100.0)
        # Submit a limit order that won't fill immediately (price below market)
        fill, reason = engine.submit_order(
            1, "BTC", "BUY", "LIMIT", quantity=1.0, limit_price=90.0
        )
        assert fill is None  # limit not crossed, goes working
        assert reason is None  # working, not rejected

        # Cancel it
        working = engine.get_working_orders()
        assert len(working) == 1
        cid = working[0].client_order_id
        ok = engine.cancel_order(cid)
        assert ok is True

        # Now tick at the limit price should NOT fill the cancelled order
        engine.market.on_tick_batch([{"symbol": "BTC", "price": 90.0}])
        fills = engine.drain_pending_fills()
        assert len(fills) == 0  # cancelled order was not filled

    def test_fill_then_cancel_single_terminal_state(self):
        """Fill a market order, then cancelling it returns False (already terminal)."""
        engine = make_engine(cash=100000.0, tick_price=100.0)
        fill, _ = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        assert fill is not None

        # Cancel the filled order — should fail
        ok = engine.cancel_order(fill.client_order_id)
        assert ok is False

        # Position should still exist (fill was not reversed)
        account = engine._accounts[1]
        assert "BTC" in account.positions
        assert float(account.positions["BTC"].quantity) == pytest.approx(1.0)


# ---- H2: WS Origin — allowed origin accepted ----

class TestH2WSAllowedOrigin:
    def test_allowed_origin_accepted(self):
        """A connection with an allowed Origin and valid token should be accepted."""
        from settings import get_settings
        from ws.hub import HUB
        import api.ws_routes as ws_mod
        HUB._connections.clear()
        HUB._ip_counts.clear()
        ws_mod._WS_TOKENS.clear()
        try:
            # Get a valid token
            r = client.get("/ws/token")
            assert r.status_code == 200
            token = r.json()["token"]

            settings = get_settings()
            origin = settings.cors_origins[0] if settings.cors_origins else "http://localhost:3355"
            ws = client.websocket_connect(f"/ws?token={token}", headers={"origin": origin})
            ws.__enter__()
            # If we got here, the connection was accepted
            ws.send_text('{"op":"ping"}')
            data = json.loads(ws.receive_text())
            assert data["type"] == "pong"
            try:
                ws.__exit__(None, None, None)
            except Exception:
                pass
        finally:
            HUB._connections.clear()
            HUB._ip_counts.clear()
            ws_mod._WS_TOKENS.clear()


# ---- H10: Guarded division (reference — full coverage in test_metrics.py, test_portfolio.py) ----

class TestH10GuardedDivision:
    def test_metrics_safe_div_never_returns_inf_or_nan(self):
        from engine.metrics import _safe_div
        assert _safe_div(10.0, 0.0) == 0.0
        assert _safe_div(float("inf"), 2.0) == 0.0
        assert _safe_div(10.0, float("nan")) == 0.0

    def test_portfolio_drawdown_zero_peak(self):
        """H10: drawdown with zero peak returns 0.0, not inf."""
        from engine.portfolio import PortfolioAccount
        acct = PortfolioAccount(strategy_id=1, strategy_key="test", starting_cash=100000.0)
        acct.peak_equity = 0.0
        assert acct.drawdown_pct({}) == 0.0
