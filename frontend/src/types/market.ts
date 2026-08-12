export interface Asset {
  id: number;
  symbol: string;
  name: string;
}

export interface PriceTicker {
  id: number;
  symbol: string;
  price: number;
  timestamp: string;
}

export interface Candle {
  symbol: string;
  interval: string;
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  trades: number;
  source: string;
}
