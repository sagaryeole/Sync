from sqlalchemy.orm import Session
from sqlalchemy import and_
from models import PriceTicker, Portfolio, TradeLog, Asset
from datetime import datetime, timezone, timedelta
import config


def generate_mock_price(session: Session):
    """Update current prices by random walk and add new price records."""
    for asset in config.ASSETS:
        # Latest recorded price
        last = session.query(PriceTicker).filter_by(
            symbol=asset["symbol"]
        ).order_by(PriceTicker.timestamp.desc()).first()
        if not last:
            continue

        # Add new price point (next minute)
        base_price = float(last.price)
        volatility = {"BTC": 0.01, "ETH": 0.015, "SOL": 0.025}[asset["symbol"]]
        drift = 0  # no trend for simplicity
        noise = volatility
        new_price = base_price * (1 + drift * 0.1)
        new_price = new_price * (1 + (-1 if last.timestamp.minute % 2 == 0 else 1) * noise)

        session.add(PriceTicker(
            symbol=asset["symbol"],
            price=new_price,
            timestamp=datetime.now(timezone.utc)
        ))
        session.commit()


def compute_ma(session: Session, symbol: str):
    """Compute simple moving average over BOT_PERIOD minutes."""
    prices = session.query(PriceTicker).filter(
        PriceTicker.symbol == symbol
    ).order_by(PriceTicker.timestamp.desc()).limit(config.BOT_PERIOD).all()
    if len(prices) < config.BOT_PERIOD:
        return None
    return sum(float(p.price) for p in prices) / len(prices)


def get_signal(session: Session, symbol: str):
    """Get the trading signal for an asset: BUY, SELL, or NONE."""
    current_price = session.query(PriceTicker).filter(
        PriceTicker.symbol == symbol
    ).order_by(PriceTicker.timestamp.desc()).first()
    if not current_price:
        return None
    ma = compute_ma(session, symbol)
    if ma is None:
        return None
    ratio = float(current_price.price) / ma
    if ratio < 0.98:
        return "BUY"
    elif ratio > 1.02:
        return "SELL"
    return None


def execute_trade(session: Session, trade_type: str, symbol: str, quantity: float, price: float):
    """Execute trade: convert USD to coin (BUY) or coin to USD (SELL).

    This is the single source of truth for portfolio updates. It handles:
    - Deducting USD from the USD portfolio on BUY
    - Crediting USD to the USD portfolio on SELL
    - Weighted-average cost basis on BUY
    - Cost basis reduction on SELL
    - Trade logging
    """
    timestamp = datetime.now(timezone.utc)
    quantity = float(quantity)
    price = float(price)

    # Ensure coin portfolio exists
    coin_portfolio = session.query(Portfolio).filter_by(symbol=symbol).first()
    if not coin_portfolio:
        coin_portfolio = Portfolio(symbol=symbol, balance=0, quantity=0, cost_basis=0)
        session.add(coin_portfolio)
        session.flush()  # get the row into the DB so subsequent queries see it

    usd_portfolio = session.query(Portfolio).filter_by(symbol="USD").first()

    if trade_type == "BUY":
        cost = quantity * price
        # Check USD balance
        if not usd_portfolio or float(usd_portfolio.balance) < cost:
            return False  # insufficient USD

        # Deduct USD
        usd_portfolio.balance = float(usd_portfolio.balance) - cost

        # Weighted-average cost basis: (old_qty * old_cb + new_qty * price) / total_qty
        old_qty = float(coin_portfolio.quantity)
        old_cb = float(coin_portfolio.cost_basis)
        new_qty = old_qty + quantity
        if new_qty > 0:
            new_cb = (old_qty * old_cb + quantity * price) / new_qty
        else:
            new_cb = 0

        # Update coin portfolio: balance tracks USD value of position (negative = invested)
        coin_portfolio.balance = float(coin_portfolio.balance) - cost
        coin_portfolio.quantity = new_qty
        coin_portfolio.cost_basis = new_cb

    else:  # SELL
        if float(coin_portfolio.quantity) <= 0:
            return False  # nothing to sell

        qty_to_sell = min(float(coin_portfolio.quantity), quantity)
        revenue = qty_to_sell * price

        # Credit USD
        if usd_portfolio:
            usd_portfolio.balance = float(usd_portfolio.balance) + revenue

        # Update coin portfolio
        remaining_qty = float(coin_portfolio.quantity) - qty_to_sell
        # Cost basis stays the same per coin; total invested decreases proportionally
        if remaining_qty > 0:
            coin_portfolio.balance = float(coin_portfolio.balance) + revenue
            coin_portfolio.quantity = remaining_qty
        else:
            # Sold everything — reset cost basis
            coin_portfolio.balance = float(coin_portfolio.balance) + revenue
            coin_portfolio.quantity = 0
            coin_portfolio.cost_basis = 0

    # Log trade
    session.add(TradeLog(
        type=trade_type, symbol=symbol,
        quantity=quantity, price=price, timestamp=timestamp
    ))
    session.commit()
    return True


def run_bot_cycle(session: Session):
    """Execute one cycle of bot: generate new prices, then decide and execute trades."""
    # Update prices for all assets
    generate_mock_price(session)

    # Trade decisions based on signal
    for asset in config.ASSETS:
        signal = get_signal(session, asset["symbol"])
        if not signal:
            continue

        # Get latest price for this asset
        latest = session.query(PriceTicker).filter_by(symbol=asset["symbol"]).order_by(
            PriceTicker.timestamp.desc()
        ).first()
        if not latest:
            continue
        price = float(latest.price)

        if signal == "BUY":
            # Bot trades $100 USD per BUY cycle
            portfolio_usd = session.query(Portfolio).filter_by(symbol="USD").first()
            if not portfolio_usd or float(portfolio_usd.balance) < 100:
                continue  # cannot buy
            quantity = 100 / price
            execute_trade(session, "BUY", asset["symbol"], quantity, price)
        else:  # SELL
            portfolio = session.query(Portfolio).filter_by(symbol=asset["symbol"]).first()
            if not portfolio or float(portfolio.quantity) <= 0:
                continue  # cannot sell
            quantity = float(portfolio.quantity)
            execute_trade(session, "SELL", asset["symbol"], quantity, price)

    session.commit()


def prune_old_prices(session: Session, max_age_hours: int = 24):
    """Delete price records older than max_age_hours to prevent unbounded table growth."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    session.query(PriceTicker).filter(PriceTicker.timestamp < cutoff).delete()
    session.commit()


def start_bot():
    """Start the background scheduler."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from database import get_session

    scheduler = BackgroundScheduler()

    def bot_job():
        session = get_session()
        try:
            run_bot_cycle(session)
        finally:
            session.close()

    def prune_job():
        session = get_session()
        try:
            prune_old_prices(session, max_age_hours=config.PRICE_RETENTION_HOURS)
        finally:
            session.close()

    scheduler.add_job(
        bot_job,
        "interval",
        seconds=config.SCHEDULER_INTERVAL,
        id="bot_cycle",
        replace_existing=True
    )
    # Prune old prices every hour
    scheduler.add_job(
        prune_job,
        "interval",
        hours=1,
        id="prune_prices",
        replace_existing=True
    )
    scheduler.start()
    return scheduler