import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import List, AsyncIterator
import httpx
import websockets
from feeds.base import MarketFeed, Tick
from feeds.symbols import to_provider, from_provider

logger = logging.getLogger("feed.binance")

def _reject(constant: str):
    raise ValueError(f"Invalid numeric constant in JSON: {constant}")

class BinanceFeed(MarketFeed):
    @property
    def name(self) -> str:
        return "binance"

    async def stream(self, symbols: List[str]) -> AsyncIterator[Tick]:
        base_uri = "wss://stream.binance.com:9443/stream?streams="
        streams = [f"{to_provider(sym, 'binance').lower()}@ticker" for sym in symbols if to_provider(sym, 'binance')]
        
        if not streams:
            logger.warning("No Binance streams configured for symbols: %s", symbols)
            return

        uri = base_uri + "/".join(streams)

        while True:
            try:
                logger.info("Connecting to Binance WebSocket: %s", uri)
                async with websockets.connect(uri, max_size=2**20) as ws:  # H12: 1MB max frame
                    async for raw_msg in ws:
                        try:
                            msg = json.loads(raw_msg, parse_constant=_reject)
                        except Exception as e:
                            logger.error("JSON parse error on Binance message: %s", e)
                            continue

                        data = msg.get("data")
                        if not data:
                            continue

                        provider_sym = data.get("s")
                        symbol = from_provider(provider_sym, "binance")
                        if not symbol:
                            continue

                        # E: Event time in ms
                        ms_time = data.get("E")
                        if ms_time:
                            ts = datetime.fromtimestamp(ms_time / 1000.0, timezone.utc)
                        else:
                            ts = datetime.now(timezone.utc)

                        try:
                            price = float(data["c"])
                            bid = float(data.get("b", price))
                            ask = float(data.get("a", price))
                            volume_24h = float(data.get("v", 0))
                            change_24h_pct = float(data.get("P", 0))

                            # H1 Validation gate
                            if price <= 0 or bid <= 0 or ask <= 0 or bid > ask:
                                logger.warning("Binance invalid price bounds: price=%f, bid=%f, ask=%f", price, bid, ask)
                                continue

                            yield Tick(
                                symbol=symbol,
                                price=price,
                                ts=ts,
                                source=self.name,
                                bid=bid,
                                ask=ask,
                                volume_24h=volume_24h,
                                change_24h_pct=change_24h_pct,
                                seq=None
                            )
                        except (KeyError, ValueError) as e:
                            logger.error("Value extraction error from Binance ticker: %s", e)

            except (websockets.exceptions.ConnectionClosed, OSError) as e:
                logger.warning("Binance connection closed/failed: %s. Reconnecting in 5s...", e)
                await asyncio.sleep(5)
            except Exception as e:
                logger.error("Unexpected error in Binance stream: %s. Restarting stream...", e)
                await asyncio.sleep(5)

    async def healthy(self) -> bool:
        """Query Binance public REST API health check."""
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get("https://api.binance.com/api/v3/ping", timeout=5.0)
                return r.status_code == 200
        except Exception as e:
            logger.warning("Binance health check failed: %s", e)
            return False
