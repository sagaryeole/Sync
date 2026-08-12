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

export interface StrategyMetrics {
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  max_drawdown_pct: number;
  intraday_sharpe: number;
  trade_count: number;
  avg_hold_time_seconds: number;
}
