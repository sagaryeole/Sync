import { create } from 'zustand';
import api from './api';

// ---- Types ----

interface PriceTicker {
  id: number;
  symbol: string;
  price: number;
  timestamp: string;
}

interface PortfolioItem {
  symbol: string;
  balance: number;
  quantity: number;
  cost_basis: number;
}

interface TradeLogItem {
  id: number;
  type: string;
  symbol: string;
  quantity: number;
  price: number;
  timestamp: string;
}

type Signal = 'BUY' | 'SELL' | null;

interface TradeResult {
  status: string;
  type: string;
  symbol: string;
  quantity: number;
  price: number;
}

// ---- Store ----

interface AppState {
  // Data
  prices: PriceTicker[];
  latestPrices: Record<string, number>;
  portfolio: PortfolioItem[];
  signals: Record<string, Signal>;
  trades: TradeLogItem[];

  // Status
  loading: boolean;
  error: string | null;

  // Actions
  fetchPrices: () => Promise<void>;
  fetchPortfolio: () => Promise<void>;
  fetchSignals: () => Promise<void>;
  fetchTrades: () => Promise<void>;
  fetchAll: () => Promise<void>;
  executeTrade: (type: string, symbol: string, quantity: number) => Promise<TradeResult | null>;
  clearError: () => void;
}

export const useStore = create<AppState>((set, get) => ({
  prices: [],
  latestPrices: {},
  portfolio: [],
  signals: {},
  trades: [],
  loading: false,
  error: null,

  fetchPrices: async () => {
    try {
      const res = await api.get<PriceTicker[]>('/prices');
      const data = Array.isArray(res.data) ? res.data : [];
      // Build latest-price-per-symbol map (data comes newest-first)
      const latest: Record<string, number> = {};
      for (const p of data) {
        if (p && p.symbol && !(p.symbol in latest)) {
          latest[p.symbol] = Number(p.price);
        }
      }
      set({ prices: data, latestPrices: latest });
    } catch (err) {
      console.error('Failed to fetch prices:', err);
      set({ error: 'Failed to fetch prices' });
    }
  },

  fetchPortfolio: async () => {
    try {
      const res = await api.get<PortfolioItem[]>('/portfolio');
      const data = Array.isArray(res.data) ? res.data : [];
      set({ portfolio: data });
    } catch (err) {
      console.error('Failed to fetch portfolio:', err);
      set({ error: 'Failed to fetch portfolio' });
    }
  },

  fetchSignals: async () => {
    try {
      const res = await api.get<Record<string, string | null>>('/bot/signals');
      set({ signals: (res.data || {}) as Record<string, Signal> });
    } catch (err) {
      console.error('Failed to fetch signals:', err);
      set({ error: 'Failed to fetch signals' });
    }
  },

  fetchTrades: async () => {
    try {
      const res = await api.get<TradeLogItem[]>('/trades?limit=10');
      const data = Array.isArray(res.data) ? res.data : [];
      set({ trades: data });
    } catch (err) {
      console.error('Failed to fetch trades:', err);
      set({ error: 'Failed to fetch trades' });
    }
  },

  fetchAll: async () => {
    set({ loading: true, error: null });
    try {
      await Promise.all([
        get().fetchPrices(),
        get().fetchPortfolio(),
        get().fetchSignals(),
        get().fetchTrades(),
      ]);
    } finally {
      set({ loading: false });
    }
  },

  executeTrade: async (type: string, symbol: string, quantity: number) => {
    try {
      const res = await api.post<TradeResult>('/trade', { type, symbol, quantity });
      // Refresh data after a successful trade
      await get().fetchAll();
      return res.data;
    } catch (err) {
      console.error('Failed to execute trade:', err);
      set({ error: 'Failed to execute trade' });
      return null;
    }
  },

  clearError: () => set({ error: null }),
}));
