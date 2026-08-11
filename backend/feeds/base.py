from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, AsyncIterator

@dataclass(frozen=True)
class Tick:
    symbol: str
    price: float
    ts: datetime
    source: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume_24h: Optional[float] = None
    change_24h_pct: Optional[float] = None
    seq: Optional[int] = None

class MarketFeed(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the feed provider (e.g. coinbase, binance, synthetic)."""
        pass

    @abstractmethod
    async def stream(self, symbols: List[str]) -> AsyncIterator[Tick]:
        """Stream ticks for the given symbols from the feed provider."""
        pass

    @abstractmethod
    async def healthy(self) -> bool:
        """Health check for the feed provider (e.g. check connection or REST ping)."""
        pass
