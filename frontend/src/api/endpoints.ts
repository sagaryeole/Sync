import api from '../api';

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

export interface BotSignals {
  [symbol: string]: string | null;
}

export async function fetchAssets(): Promise<Asset[]> {
  const { data } = await api.get('/assets');
  return data;
}

export async function fetchAsset(symbol: string): Promise<Asset> {
  const { data } = await api.get(`/assets/${encodeURIComponent(symbol)}`);
  return data;
}

export async function fetchPrices(params?: { asset?: string; start?: string }): Promise<PriceTicker[]> {
  const { data } = await api.get('/prices', { params });
  return data;
}

export async function fetchPortfolio(): Promise<PortfolioItem[]> {
  const { data } = await api.get('/portfolio');
  return data;
}

export async function fetchPortfolioItem(symbol: string): Promise<PortfolioItem> {
  const { data } = await api.get(`/portfolio/${encodeURIComponent(symbol)}`);
  return data;
}

export async function executeTrade(payload: { type: 'BUY' | 'SELL'; symbol: string; quantity: number }) {
  const { data } = await api.post('/trade', payload);
  return data;
}

export async function fetchTrades(params?: { limit?: number; offset?: number }): Promise<TradeLog[]> {
  const { data } = await api.get('/trades', { params });
  return data;
}

export async function fetchBotSignals(): Promise<BotSignals> {
  const { data } = await api.get('/bot/signals');
  return data;
}
