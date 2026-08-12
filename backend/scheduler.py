"""Scheduler — background jobs for the paper-trading engine.

Extracted from the old ``bot.py:start_bot`` (a single MA-crossover cycle) and
replaced with the real engine's job set:

    engine_tick      1s   — working LIMIT/STOP orders, SL/TP, kill-switch
    strategy_tick    15s  — evaluate every enabled strategy on CLOSED 1m bars
    equity_snapshot  30s  — one EquitySnapshot row per strategy
    prune            1h   — trim prices/candles/equity_snapshots per retention

Candle flushing stays on its existing asyncio task in ``main.py`` (step 22/23) —
it already writes through an explicit ``get_session()``, so it already satisfies
the "event loop never opens its own session implicitly" invariant, and moving a
working, tested path here would be churn for no correctness gain.

All DB writes below happen on these APScheduler threads, never on the asyncio
event loop — see CLAUDE.md's "the event loop never touches the database".
The engine/runner themselves never open a session; every write here is a
transaction owned by this module (H5: fill + position/cash update together).
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from database import get_session
from engine.logging import set_correlation_id
from engine.core import PaperEngine
from engine.market_state import MarketState
from engine.runner import RunnerStrategyConfig, StrategyRunner
from models import (
    Candle,
    EquitySnapshot,
    Fill as FillModel,
    Order as OrderModel,
    Position as PositionModel,
    PortfolioAccount as PortfolioAccountModel,
    PriceTicker,
    Signal,
    Strategy as StrategyModel,
)
from strategies.base import Action, Candle as StrategyCandle
from strategies.schemas import validate_params
from settings import get_settings

logger = logging.getLogger("scheduler")


# ---------------------------------------------------------------------------
# DB-backed providers injected into the DB-agnostic StrategyRunner
# ---------------------------------------------------------------------------

def _candle_provider(symbol: str, limit: int):
    session = get_session()
    try:
        rows = (
            session.query(Candle)
            .filter_by(symbol=symbol, interval="1m")
            .order_by(Candle.open_time.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        return [
            StrategyCandle(
                symbol=r.symbol,
                open_time=int(r.open_time.timestamp()),
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=float(r.volume),
                trades=r.trades or 0,
            )
            for r in rows
        ]
    finally:
        session.close()


def _strategy_configs() -> list:
    session = get_session()
    try:
        rows = session.query(StrategyModel).filter_by(enabled=True).all()
        configs = []
        for r in rows:
            if r.key == "manual":
                continue  # the manual strategy is the user's own portfolio, not algorithmic
            params = {}
            if r.params_json:
                try:
                    raw = json.loads(r.params_json)
                    if isinstance(raw, dict):
                        params = validate_params(r.key, raw)
                except (TypeError, ValueError):
                    params = {}
            configs.append(RunnerStrategyConfig(strategy_id=r.id, key=r.key, params=params))
        return configs
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Persistence helpers (H5: fill + derived-cache update in one transaction)
# ---------------------------------------------------------------------------

def _persist_fills(session, fills) -> None:
    """Persist Order + Fill rows for a batch of engine fills, one transaction (H5).

    ``f.realized_pnl`` comes from the broker (computed against the pre-fill
    avg entry price before ``apply_fill`` mutates it) — 0.0 for every BUY,
    the realized amount for a SELL.
    """
    for f in fills:
        liquidity = "MAKER" if f.order_type == "LIMIT" else "TAKER"
        order_row = OrderModel(
            client_order_id=f.client_order_id,
            strategy_id=f.strategy_id,
            symbol=f.symbol,
            side=f.side,
            order_type=f.order_type,
            quantity=f.quantity,
            status="FILLED",
            filled_quantity=f.quantity,
            avg_fill_price=f.price,
            created_at=f.ts,
            updated_at=f.ts,
        )
        session.add(order_row)
        session.flush()  # assign order_row.id
        session.add(FillModel(
            order_id=order_row.id,
            strategy_id=f.strategy_id,
            symbol=f.symbol,
            side=f.side,
            quantity=f.quantity,
            price=f.price,
            fee=f.fee,
            realized_pnl=f.realized_pnl,
            mark_price=f.price,
            liquidity=liquidity,
            ts=f.ts,
        ))


def _persist_signals(session, results) -> None:
    for r in results:
        if r.decision.action == Action.HOLD:
            continue  # step 35: persist signals rows only when action != HOLD
        session.add(Signal(
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            action=r.decision.action,
            strength=r.decision.strength,
            price=r.last_price,
            indicators_json=json.dumps(r.decision.indicators or {}),
        ))


def _sync_account(session, account) -> None:
    """Upsert the portfolios + positions cache rows for one account.

    These tables are a derived cache (H5) — ``fills`` is the source of truth.
    Full crash-recovery replay from ``fills`` is not implemented yet (H5 is
    still open); this keeps the cache close to live state across a clean
    restart, it does not protect against a mid-mutation crash.
    """
    now = datetime.now(timezone.utc)
    stmt = sqlite_insert(PortfolioAccountModel).values(
        strategy_id=account.strategy_id,
        cash=account.cash,
        realized_pnl=account.realized_pnl,
        fees_paid=account.fees_paid,
        peak_equity=account.peak_equity,
        is_halted=account.is_halted,
        halt_reason=account.halt_reason,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["strategy_id"],
        set_={
            "cash": stmt.excluded.cash,
            "realized_pnl": stmt.excluded.realized_pnl,
            "fees_paid": stmt.excluded.fees_paid,
            "peak_equity": stmt.excluded.peak_equity,
            "is_halted": stmt.excluded.is_halted,
            "halt_reason": stmt.excluded.halt_reason,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)

    for symbol, pos in account.positions.items():
        pstmt = sqlite_insert(PositionModel).values(
            strategy_id=account.strategy_id,
            symbol=symbol,
            quantity=pos.quantity,
            avg_entry_price=pos.avg_entry_price,
            realized_pnl=0.0,
            stop_loss_price=pos.stop_loss_price,
            take_profit_price=pos.take_profit_price,
            opened_at=pos.opened_at or now,
            updated_at=now,
        )
        pstmt = pstmt.on_conflict_do_update(
            index_elements=["strategy_id", "symbol"],
            set_={
                "quantity": pstmt.excluded.quantity,
                "avg_entry_price": pstmt.excluded.avg_entry_price,
                "stop_loss_price": pstmt.excluded.stop_loss_price,
                "take_profit_price": pstmt.excluded.take_profit_price,
                "updated_at": pstmt.excluded.updated_at,
            },
        )
        session.execute(pstmt)


def _flush_engine_state(engine: PaperEngine) -> None:
    """Drain pending fills and sync the portfolio/position cache in one transaction."""
    fills = engine.drain_pending_fills()
    if not fills:
        return
    session = get_session()
    try:
        _persist_fills(session, fills)
        touched = {f.strategy_id for f in fills}
        for strategy_id in touched:
            account = engine.get_account(strategy_id)
            if account is not None:
                _sync_account(session, account)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Failed to flush engine fills/positions to DB")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def _make_engine_tick_job(engine: PaperEngine):
    def job():
        with set_correlation_id():
            try:
                engine.on_tick_batch()
                _flush_engine_state(engine)
            except Exception:
                logger.exception("engine_tick job failed")
    return job


def _make_strategy_tick_job(engine: PaperEngine, market: MarketState, symbols, feed_manager):
    runner = StrategyRunner(
        engine, market, _candle_provider, symbols,
        symbol_filter=feed_manager.is_symbol_tradable,
    )

    def job():
        with set_correlation_id():
            try:
                configs = _strategy_configs()
                if not configs:
                    return
                results = runner.run_all(configs)
                if results:
                    session = get_session()
                    try:
                        _persist_signals(session, results)
                        session.commit()
                    except Exception:
                        session.rollback()
                        logger.exception("Failed to persist signals")
                    finally:
                        session.close()
                _flush_engine_state(engine)
            except Exception:
                logger.exception("strategy_tick job failed")
    return job


def _make_equity_snapshot_job(engine: PaperEngine, market: MarketState):
    def job():
        with set_correlation_id():
            session = get_session()
            try:
                marks = market.snapshot()
                now = datetime.now(timezone.utc)
                for strategy_id, account in engine.get_all_accounts().items():
                    session.add(EquitySnapshot(
                        strategy_id=strategy_id,
                        ts=now,
                        equity=account.equity(marks),
                        cash=account.cash,
                        position_value=account.position_value(marks),
                        realized_pnl=account.realized_pnl,
                        unrealized_pnl=account.unrealized_pnl(marks),
                        drawdown_pct=account.drawdown_pct(marks),
                    ))
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("equity_snapshot job failed")
            finally:
                session.close()
    return job


def _make_prune_job():
    def job():
        with set_correlation_id():
            settings = get_settings()
            session = get_session()
            try:
                now = datetime.now(timezone.utc)
                price_cutoff = now - timedelta(hours=24)
                session.query(PriceTicker).filter(PriceTicker.timestamp < price_cutoff).delete()

                candle_cutoff = now - timedelta(days=settings.candle_retention_days)
                session.query(Candle).filter(Candle.open_time < candle_cutoff).delete()

                equity_cutoff = now - timedelta(hours=settings.equity_retention_hours)
                session.query(EquitySnapshot).filter(EquitySnapshot.ts < equity_cutoff).delete()

                session.commit()
            except Exception:
                session.rollback()
                logger.exception("prune job failed")
            finally:
                session.close()
    return job


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def start_scheduler(engine: PaperEngine, market: MarketState, symbols, feed_manager) -> BackgroundScheduler:
    """Build and start the engine's background job scheduler."""
    settings = get_settings()
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        _make_engine_tick_job(engine),
        "interval",
        seconds=settings.engine_tick_seconds,
        id="engine_tick",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=5,
        replace_existing=True,
    )
    scheduler.add_job(
        _make_strategy_tick_job(engine, market, symbols, feed_manager),
        "interval",
        seconds=settings.strategy_interval_seconds,
        id="strategy_tick",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=10,
        replace_existing=True,
    )
    scheduler.add_job(
        _make_equity_snapshot_job(engine, market),
        "interval",
        seconds=settings.equity_snapshot_seconds,
        id="equity_snapshot",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=15,
        replace_existing=True,
    )
    scheduler.add_job(
        _make_prune_job(),
        "interval",
        hours=1,
        id="prune",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Engine scheduler started: engine_tick=%ss strategy_tick=%ss equity_snapshot=%ss prune=1h",
                settings.engine_tick_seconds, settings.strategy_interval_seconds, settings.equity_snapshot_seconds)
    return scheduler
