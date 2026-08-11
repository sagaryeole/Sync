from typing import Optional, Dict

SYMBOLS = {
    "BTC": {
        "name": "Bitcoin",
        "coinbase": "BTC-USD",
        "binance": "BTCUSDT",
        "price_dp": 2,
        "qty_dp": 6,
        "seed": 65000.0,
        "vol": 0.55
    },
    "ETH": {
        "name": "Ethereum",
        "coinbase": "ETH-USD",
        "binance": "ETHUSDT",
        "price_dp": 2,
        "qty_dp": 5,
        "seed": 1925.0,
        "vol": 0.65
    },
    "SOL": {
        "name": "Solana",
        "coinbase": "SOL-USD",
        "binance": "SOLUSDT",
        "price_dp": 2,
        "qty_dp": 4,
        "seed": 150.0,
        "vol": 0.85
    },
    "XRP": {
        "name": "Ripple",
        "coinbase": "XRP-USD",
        "binance": "XRPUSDT",
        "price_dp": 4,
        "qty_dp": 1,
        "seed": 0.56,
        "vol": 0.75
    },
    "ADA": {
        "name": "Cardano",
        "coinbase": "ADA-USD",
        "binance": "ADAUSDT",
        "price_dp": 4,
        "qty_dp": 1,
        "seed": 0.38,
        "vol": 0.70
    },
    "DOGE": {
        "name": "Dogecoin",
        "coinbase": "DOGE-USD",
        "binance": "DOGEUSDT",
        "price_dp": 5,
        "qty_dp": 0,
        "seed": 0.12,
        "vol": 0.90
    },
    "AVAX": {
        "name": "Avalanche",
        "coinbase": "AVAX-USD",
        "binance": "AVAXUSDT",
        "price_dp": 2,
        "qty_dp": 3,
        "seed": 22.0,
        "vol": 0.80
    },
    "LINK": {
        "name": "Chainlink",
        "coinbase": "LINK-USD",
        "binance": "LINKUSDT",
        "price_dp": 3,
        "qty_dp": 3,
        "seed": 13.5,
        "vol": 0.75
    }
}

def to_provider(symbol: str, provider: str) -> Optional[str]:
    """Map dynamic app symbol to Coinbase/Binance string."""
    cfg = SYMBOLS.get(symbol)
    if cfg:
        return cfg.get(provider)
    return None

def from_provider(pid: str, provider: str) -> Optional[str]:
    """Map Coinbase/Binance symbol back to dynamic app symbol."""
    for symbol, cfg in SYMBOLS.items():
        if cfg.get(provider) == pid:
            return symbol
        # Also try case insensitive mapping for Binance (e.g. btcusdt -> BTC)
        if provider == "binance" and cfg.get(provider).lower() == pid.lower():
            return symbol
    return None

def is_tradable(symbol: str) -> bool:
    """Check if symbol is defined in our registry."""
    return symbol in SYMBOLS
