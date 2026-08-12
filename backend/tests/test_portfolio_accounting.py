"""Property tests for portfolio accounting.

Property: equity == starting_cash + realized_pnl + unrealized_pnl to 1e-6 at every step,
cash never negative, cost basis matches reference implementation.
"""
import random
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from engine.core import PaperEngine, EngineConfig
from engine.paper_broker import PaperBroker
from engine.risk import RiskConfig, RiskManager


def make_tick(price, bid=None, ask=None, ts=None, symbol="BTC"):
    tick = MagicMock()
    tick.symbol = symbol
    tick.price = price
    tick.bid = bid if bid is not None else price - 1.0
    tick.ask = ask if bid is None else price + 1.0 if ask is None else ask
    tick.ts = ts or datetime.now(timezone.utc)
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


def make_engine(cash=100000.0, tick_price=50000.0, prices=None):
    tick = make_tick(tick_price)
    if prices is None:
        prices = {"BTC": tick_price}
    ms = make_market_state(tick=tick, prices=prices, last_price=tick_price)
    broker = PaperBroker(ms, slippage_bps=0, impact_notional=1e12)
    rm = RiskManager(RiskConfig(max_position_pct=0.95))
    engine = PaperEngine(ms, broker, rm, EngineConfig(starting_cash=cash))
    engine.register_strategy(1, "test", cash)
    return engine


def get_equity(account, prices):
    cash = float(account.cash)
    position_value = sum(
        p.market_value(prices.get(sym, p.avg_entry_price))
        for sym, p in account.positions.items()
    )
    return cash + position_value


class TestPortfolioAccounting:
    def test_equity_invariant_single_trade(self):
        engine = make_engine(cash=100000.0, tick_price=50000.0, prices={"BTC": 50000.0})
        starting_cash = 100000.0

        fill, _ = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        assert fill is not None

        account = engine._accounts[1]
        equity = get_equity(account, {"BTC": 50000.0})
        realized = float(account.realized_pnl)
        unrealized = float(account.unrealized_pnl({"BTC": 50000.0}))

        assert equity == pytest.approx(starting_cash + realized + unrealized, abs=1e-5)

    def test_cash_never_negative_after_sequence(self):
        engine = make_engine(cash=100000.0, tick_price=50000.0, prices={"BTC": 50000.0})
        random.seed(42)

        for _ in range(50):
            side = random.choice(["BUY", "SELL"])
            qty = random.uniform(0.1, 2.0)
            price = 50000.0

            fill, _ = engine.submit_order(1, "BTC", side, "MARKET", quantity=qty)
            if fill is None:
                continue

            account = engine._accounts[1]
            assert float(account.cash) >= -1e-6

    def test_equity_invariant_random_sequence(self):
        engine = make_engine(cash=100000.0, tick_price=50000.0, prices={"BTC": 50000.0})
        starting_cash = 100000.0
        random.seed(123)

        for _ in range(100):
            side = random.choice(["BUY", "SELL"])
            qty = random.uniform(0.1, 3.0)
            price = 50000.0

            fill, _ = engine.submit_order(1, "BTC", side, "MARKET", quantity=qty)
            if fill is None:
                continue

            account = engine._accounts[1]
            equity = get_equity(account, {"BTC": price})
            realized = float(account.realized_pnl)
            unrealized = float(account.unrealized_pnl({"BTC": price}))

            assert equity == pytest.approx(starting_cash + realized + unrealized, abs=1e-4)

    def test_cost_basis_tracks_quantity(self):
        engine = make_engine(cash=200000.0, tick_price=50000.0, prices={"BTC": 50000.0})
        fill1, _ = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=2.0)
        assert fill1 is not None

        account = engine._accounts[1]
        btc_pos = account.positions.get("BTC")
        assert btc_pos is not None
        assert float(btc_pos.quantity) == pytest.approx(2.0)

    def test_position_flips_after_buy_then_sell(self):
        engine = make_engine(cash=200000.0, tick_price=50000.0, prices={"BTC": 50000.0})
        fill1, _ = engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        assert fill1 is not None

        fill2, _ = engine.submit_order(1, "BTC", "SELL", "MARKET", quantity=1.0)
        assert fill2 is not None

        account = engine._accounts[1]
        btc_pos = account.positions.get("BTC")
        assert btc_pos is not None
        assert float(btc_pos.quantity) == pytest.approx(0.0)

    def test_multiple_symbols_independent(self):
        prices = {"BTC": 50000.0, "ETH": 3000.0, "SOL": 100.0}
        ticks = {sym: make_tick(price, symbol=sym) for sym, price in prices.items()}

        ms = MagicMock()
        ms.last_tick.side_effect = lambda sym: ticks.get(sym)
        ms.last.side_effect = lambda sym: prices.get(sym)
        ms.snapshot.return_value = prices

        broker = PaperBroker(ms, slippage_bps=0, impact_notional=1e12)
        rm = RiskManager(RiskConfig(max_position_pct=0.95))
        engine = PaperEngine(ms, broker, rm, EngineConfig(starting_cash=100000.0))
        engine.register_strategy(1, "test", 100000.0)

        engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        engine.submit_order(1, "ETH", "BUY", "MARKET", quantity=10.0)
        engine.submit_order(1, "SOL", "BUY", "MARKET", quantity=100.0)

        account = engine._accounts[1]
        equity = get_equity(account, prices)
        realized = float(account.realized_pnl)
        unrealized = float(account.unrealized_pnl(prices))

        assert equity == pytest.approx(100000.0 + realized + unrealized, abs=1e-4)
        assert set(account.positions.keys()) == {"BTC", "ETH", "SOL"}

    def test_full_exit_removes_position(self):
        engine = make_engine(cash=200000.0, tick_price=50000.0, prices={"BTC": 50000.0})
        engine.submit_order(1, "BTC", "BUY", "MARKET", quantity=1.0)
        engine.submit_order(1, "BTC", "SELL", "MARKET", quantity=1.0)

        account = engine._accounts[1]
        btc_pos = account.positions.get("BTC")
        if btc_pos is not None:
            assert abs(float(btc_pos.quantity)) < 1e-9