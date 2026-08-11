import asyncio
import os
import random
from datetime import datetime, timezone
from typing import List, AsyncIterator, Dict, Optional
from feeds.base import MarketFeed, Tick
from feeds.symbols import SYMBOLS

class SyntheticFeed(MarketFeed):
    def __init__(self, seed: Optional[int] = None):
        self._seed = seed
        self._rng = random.Random()
        # Seed the RNG if CTA_SYNTHETIC_SEED is set
        env_seed = os.environ.get("CTA_SYNTHETIC_SEED")
        if env_seed is not None:
            try:
                self._rng.seed(int(env_seed))
            except ValueError:
                pass
        elif self._seed is not None:
            self._rng.seed(self._seed)

    @property
    def name(self) -> str:
        return "synthetic"

    async def stream(self, symbols: List[str]) -> AsyncIterator[Tick]:
        prices: Dict[str, float] = {}
        for sym in symbols:
            cfg = SYMBOLS.get(sym)
            if cfg:
                prices[sym] = cfg["seed"]
            else:
                prices[sym] = 100.0  # default fallback

        dt = 0.5  # 2 Hz
        theta = 0.02  # mean reversion speed
        
        while True:
            for sym in symbols:
                cfg = SYMBOLS.get(sym, {"seed": 100.0, "vol": 0.5})
                target = cfg["seed"]
                vol = cfg["vol"]

                # Step volatility scaled for 2 Hz ticks
                # Annualized vol of 0.55 -> step vol roughly: 0.55 / sqrt(365 * 24 * 3600 / 0.5)
                # To make it trace realistically and move enough in real-time, we scale it
                step_vol = (vol / 200.0)
                
                current = prices[sym]
                # Ornstein-Uhlenbeck / Mean reverting GBM step
                # dS = theta * (target - S) * dt + vol * S * dW
                drift = theta * (target - current) * dt
                # random.normalvariate is built into python
                random_walk = step_vol * current * self._rng.normalvariate(0.0, 1.0)
                
                new_price = current + drift + random_walk
                if new_price <= 0:
                    new_price = 0.01

                prices[sym] = new_price

                # Fake spread of ~1-2 bps
                spread = new_price * 0.0002
                bid = new_price - spread / 2.0
                ask = new_price + spread / 2.0
                
                yield Tick(
                    symbol=sym,
                    price=new_price,
                    ts=datetime.now(timezone.utc),
                    source=self.name,
                    bid=bid,
                    ask=ask,
                    volume_24h=10000.0,
                    change_24h_pct=0.0,
                    seq=None
                )
            
            await asyncio.sleep(dt)

    async def healthy(self) -> bool:
        return True
