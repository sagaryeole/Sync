import { create } from 'zustand';
import api from '../api';
import { useMarketStore } from './marketSlice';
import { usePortfolioStore } from './portfolioSlice';

type Signal = 'BUY' | 'SELL' | null;

interface TradeLogItem {
  id: number;
  type: string;
  symbol: string;
  quantity: number;
  price: number;
  timestamp: string;
}

interface TradeResult {
  status: string;
  type: string;
  symbol: string;
  quantity: number;
  price: number;
}

interface AppState {
  signals: Record<string, Signal>;
  trades: TradeLogItem[];
  loading: boolean;
  error: string | null;
  fetchSignals: () => Promise<void>;
  fetchTrades: () => Promise<void>;
  fetchAll: () => Promise<void>;
  executeTrade: (type: string, symbol: string, quantity: number) => Promise<TradeResult | null>;
  clearError: () => void;
}

export const useStore = create<AppState>((set, get) => ({
  signals: {},
  trades: [],
  loading: false,
  error: null,

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
        useMarketStore.getState().fetchPrices(),
        usePortfolioStore.getState().fetchPortfolio(),
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
