import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import List, AsyncIterator, Dict, Optional
import httpx
import websockets
from feeds.base import MarketFeed, Tick
from feeds.symbols import to_provider, from_provider

logger = logging.getLogger("feed.coinbase")

def _reject(constant: str):
    raise ValueError(f"Invalid numeric constant in JSON: {constant}")

class CoinbaseFeed(MarketFeed):
    @property
    def name(self) -> str:
        return "coinbase"

    async def stream(self, symbols: List[str]) -> AsyncIterator[Tick]:
        uri = "wss://ws-feed.exchange.coinbase.com"
        product_ids = [to_provider(sym, "coinbase") for sym in symbols if to_provider(sym, "coinbase")]
        if not product_ids:
            logger.warning("No Coinbase products configured for symbols: %s", symbols)
            return

        last_seq: Dict[str, int] = {}

        while True:
            try:
                logger.info("Connecting to Coinbase WebSocket: %s", uri)
                async with websockets.connect(uri, max_size=2**20) as ws:  # H12: 1MB max frame
                    subscribe_msg = {
                        "type": "subscribe",
                        "product_ids": product_ids,
                        "channels": ["ticker", "heartbeats"]
                    }
                    await ws.send(json.dumps(subscribe_msg))

                    async for raw_msg in ws:
                        try:
                            msg = json.loads(raw_msg, parse_constant=_reject)
                        except Exception as e:
                            logger.error("JSON parse error on Coinbase message: %s", e)
                            continue

                        # Check for error message
                        if msg.get("type") == "error":
                            logger.error("Coinbase WebSocket error: %s", msg.get("message"))
                            continue

                        if msg.get("type") == "ticker":
                            product_id = msg.get("product_id")
                            symbol = from_provider(product_id, "coinbase")
                            if not symbol:
                                continue

                            # H11: check timestamp
                            time_str = msg.get("time")
                            if time_str:
                                try:
                                    ts = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                                except ValueError:
                                    ts = datetime.now(timezone.utc)
                            else:
                                ts = datetime.now(timezone.utc)

                            # Sequence check
                            seq = msg.get("sequence")
                            if seq is not None:
                                if product_id in last_seq:
                                    expected = last_seq[product_id] + 1
                                    if seq != expected:
                                        logger.warning(
                                            "Coinbase sequence gap on %s: expected %d, got %d",
                                            product_id, expected, seq
                                        )
                                last_seq[product_id] = seq

                            try:
                                price = float(msg["price"])
                                bid = float(msg.get("best_bid", price))
                                ask = float(msg.get("best_ask", price))
                                volume_24h = float(msg.get("volume_24h", 0))
                                
                                # H1 Validation gate
                                if price <= 0 or bid <= 0 or ask <= 0 or bid > ask:
                                    logger.warning("Coinbase invalid price bounds: price=%f, bid=%f, ask=%f", price, bid, ask)
                                    continue

                                yield Tick(
                                    symbol=symbol,
                                    price=price,
                                    ts=ts,
                                    source=self.name,
                                    bid=bid,
                                    ask=ask,
                                    volume_24h=volume_24h,
                                    change_24h_pct=None, # Ticker doesn't always have percent change directly or format differs
                                    seq=seq
                                )
                            except (KeyError, ValueError) as e:
                                logger.error("Value extraction error from Coinbase ticker: %s", e)

            except (websockets.exceptions.ConnectionClosed, OSError) as e:
                logger.warning("Coinbase connection closed/failed: %s. Reconnecting in 5s...", e)
                await asyncio.sleep(5)
            except Exception as e:
                logger.error("Unexpected error in Coinbase stream: %s. Restarting stream...", e)
                await asyncio.sleep(5)

    async def healthy(self) -> bool:
        """Query Coinbase public REST API health check."""
        try:
            async with httpx.AsyncClient() as client:
                # Get ticker for a major pair to check API responsiveness
                r = await client.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker", timeout=5.0)
                return r.status_code == 200
        except Exception as e:
            logger.warning("Coinbase health check failed: %s", e)
            return False
