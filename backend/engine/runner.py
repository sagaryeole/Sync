"""StrategyRunner — evaluates every enabled strategy against every symbol.

Runs on the 15s ``strategy_tick`` job (see ``backend/scheduler.py``). Evaluates
on CLOSED 1m bars only, never intra-bar — the candle provider is DB-backed and
the DB only ever holds closed candles (the in-progress bar lives in
``MarketState`` and is never queried here).

Per CLAUDE.md's invariant, the engine core never opens its own DB sessions —
candle history and strategy config are handed in via injected callables, kept
DB-agnostic and unit-testable in isolation.
"""
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from engine.core import PaperEngine
from engine.market_state import MarketState
from strategies.base import Action, Decision, Position as StrategyPosition, StrategyContext
from strategies.registry import get_strategy

logger = logging.getLogger("engine.runner")


@dataclass
class RunnerStrategyConfig:
    """One entry in the runner's work list — mirrors a `strategies` DB row."""
    strategy_id: int
    key: str
    params: Optional[Dict] = None


@dataclass
class RunResult:
    """Outcome of evaluating one (strategy, symbol) pair for one tick."""
    strategy_id: int
    strategy_key: str
    symbol: str
    decision: Decision
    last_price: float = 0.0
    fill: object = None                    # engine.paper_broker.Fill, if the decision traded
    reject_reason: Optional[str] = None


class StrategyRunner:
    """Evaluates every enabled strategy against every tradable symbol.

    ``candle_provider(symbol, limit) -> List[strategies.base.Candle]`` is
    injected so the runner stays DB-agnostic and testable without a database.
    """

    def __init__(
        self,
        engine: PaperEngine,
        market: MarketState,
        candle_provider: Callable[[str, int], list],
        symbols: List[str],
    ):
        self.engine = engine
        self.market = market
        self.candle_provider = candle_provider
        self.symbols = symbols

    def run_all(self, strategy_configs: List[RunnerStrategyConfig]) -> List[RunResult]:
        """Evaluate every (strategy, symbol) pair once.

        Returns one RunResult per pair that had enough warmup data to evaluate
        (pairs skipped for insufficient history are omitted, not HOLD).
        """
        results: List[RunResult] = []
        for cfg in strategy_configs:
            strategy = get_strategy(cfg.key)
            if strategy is None:
                logger.warning("Strategy key %s not found in registry, skipping", cfg.key)
                continue
            account = self.engine.get_account(cfg.strategy_id)
            if account is None:
                logger.warning("Strategy id %d not registered with engine, skipping", cfg.strategy_id)
                continue
            if account.is_halted:
                continue

            marks = self.market.snapshot()
            for symbol in self.symbols:
                result = self._run_one(strategy, cfg, account, symbol, marks)
                if result is not None:
                    results.append(result)
        return results

    def _run_one(self, strategy, cfg: RunnerStrategyConfig, account, symbol: str, marks: Dict[str, float]) -> Optional[RunResult]:
        candles = self.candle_provider(symbol, max(strategy.warmup_bars + 5, 30))
        if len(candles) < strategy.warmup_bars:
            return None

        last_price = self.market.last(symbol)
        if last_price is None:
            return None

        position = account.get_position(symbol)
        strategy_position = None
        if position is not None and position.is_open:
            strategy_position = StrategyPosition(
                symbol=symbol,
                quantity=position.quantity,
                avg_entry_price=position.avg_entry_price,
                unrealized_pnl=position.unrealized_pnl(last_price),
            )

        ctx = StrategyContext(
            symbol=symbol,
            candles=candles,
            last_price=last_price,
            position=strategy_position,
            cash=account.cash,
            equity=account.equity(marks),
            params=cfg.params or strategy.default_params,
        )

        try:
            decision = strategy.evaluate(ctx)
        except Exception:
            logger.exception("Strategy %s raised while evaluating %s", cfg.key, symbol)
            return None

        fill = None
        reject_reason = None

        if decision.action == Action.BUY:
            # Opening/adding — size through the risk manager (2% risk, capped, SL/TP attached).
            fill, reject_reason = self.engine.submit_order(
                strategy_id=cfg.strategy_id,
                symbol=symbol,
                side=Action.BUY,
                order_type="MARKET",
                quantity=None,
                attach_stops=True,
            )
        elif decision.action == Action.SELL:
            # Exiting — always flat the full position. Auto-sizing (risk % of
            # equity against a fresh stop distance) does not mean "close the
            # position I already hold", so it is never used here. Long-only:
            # a SELL signal with no open position is a no-op, not a short.
            if strategy_position is not None and strategy_position.quantity > 0:
                fill, reject_reason = self.engine.submit_order(
                    strategy_id=cfg.strategy_id,
                    symbol=symbol,
                    side=Action.SELL,
                    order_type="MARKET",
                    quantity=strategy_position.quantity,
                    attach_stops=False,
                )
            else:
                reject_reason = "NO_POSITION_TO_SELL"

        if reject_reason:
            logger.info("Strategy %s %s %s rejected: %s", cfg.key, decision.action, symbol, reject_reason)

        return RunResult(
            strategy_id=cfg.strategy_id,
            strategy_key=cfg.key,
            symbol=symbol,
            decision=decision,
            last_price=last_price,
            fill=fill,
            reject_reason=reject_reason,
        )
