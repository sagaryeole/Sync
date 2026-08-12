export interface PortfolioItem {
  symbol: string;
  balance: number;
  quantity: number;
  cost_basis: number;
}

export interface TradeLog {
  id: number;
  type: string;
  symbol: string;
  quantity: number;
  price: number;
  timestamp: string;
}

export interface Position {
  id: number;
  strategy_id: number;
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  realized_pnl: number;
  stop_loss_price: number | null;
  take_profit_price: number | null;
  opened_at: string;
  updated_at: string;
}

export interface Order {
  id: number;
  client_order_id: string;
  strategy_id: number;
  symbol: string;
  side: string;
  order_type: string;
  status: string;
  quantity: number;
  filled_quantity: number;
  filled_price: number;
  fee: number;
  reject_reason: string;
  created_at: string;
  updated_at: string;
}

export interface Fill {
  id: number;
  strategy_id: number;
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  fee: number;
  realized_pnl: number;
  liquidity: string;
  ts: string;
}

export interface Strategy {
  id: number;
  key: string;
  name: string;
  description: string;
  enabled: boolean;
  starting_cash: number;
  created_at: string;
}

/**
 * All *_pct fields are FRACTIONS (0.05 = 5%), matching engine/metrics.py.
 * Render them with fmtRatioPct, not fmtPct, or they read 100x too small.
 *
 * Fields are nullable because the API maps non-finite values to null:
 * profit_factor is legitimately infinite when there are wins but no losses,
 * and Infinity is not valid JSON.
 */
export interface StrategyMetrics {
  total_return_pct: number | null;
  win_rate: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number | null;
  intraday_sharpe: number | null;
  trade_count: number | null;
  avg_hold_time_seconds: number | null;
}
