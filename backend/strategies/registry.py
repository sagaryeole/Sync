"""Strategy registry — global mapping from strategy key to Strategy object."""
from typing import Dict, List, Optional

from strategies.base import Strategy


STRATEGIES: Dict[str, Strategy] = {}


def register(strategy: Strategy) -> Strategy:
    """Decorator / helper that adds a strategy class to the global registry."""
    if not isinstance(strategy, Strategy):
        raise TypeError(
            f"Object {strategy!r} does not implement Strategy protocol"
        )
    if strategy.key in STRATEGIES:
        raise KeyError(f"Duplicate strategy key: {strategy.key}")
    STRATEGIES[strategy.key] = strategy
    return strategy


def get_strategy(key: str) -> Optional[Strategy]:
    """Look up a strategy by key.  Returns ``None`` if not found."""
    return STRATEGIES.get(key)


def list_strategies() -> List[str]:
    """Return all registered strategy keys."""
    return list(STRATEGIES.keys())
