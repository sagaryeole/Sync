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

interface Strategy {
  id: number;
  key: string;
  name: string;
  enabled: boolean;
}

interface AppState {
  signals: Record<string, Signal>;
  trades: TradeLogItem[];
  loading: boolean;
  error: string | null;
  strategies: Strategy[];
  strategyId: number | null;
  fetchSignals: () => Promise<void>;
  fetchTrades: () => Promise<void>;
  fetchStrategies: () => Promise<void>;
  setStrategyId: (id: number) => void;
  fetchAll: () => Promise<void>;
  executeTrade: (type: string, symbol: string, quantity: number, strategyId: number) => Promise<TradeResult | null>;
  clearError: () => void;
}

export const useStore = create<AppState>((set, get) => ({
  signals: {},
  trades: [],
  loading: false,
  error: null,
  strategies: [],
  strategyId: null,

  fetchStrategies: async () => {
    try {
      const res = await api.get<Strategy[]>('/strategies');
      const data = Array.isArray(res.data) ? res.data : [];
      const enabled = data.filter(s => s.enabled);
      const strategyId = enabled.length > 0 ? enabled[0].id : (data.length > 0 ? data[0].id : null);
      set({ strategies: data, strategyId });
    } catch (err) {
      console.error('Failed to fetch strategies:', err);
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
      const state = get();
      if (!state.strategies.length) {
        await get().fetchStrategies();
      }
      await Promise.all([
        useMarketStore.getState().fetchPrices(),
        usePortfolioStore.getState().fetchPortfolio(get().strategyId),
        get().fetchSignals(),
        get().fetchTrades(),
      ]);
    } finally {
      set({ loading: false });
    }
  },

  executeTrade: async (type: string, symbol: string, quantity: number, strategyId: number) => {
    try {
      const res = await api.post('/orders', null, {
        params: {
          strategy_id: strategyId,
          symbol,
          side: type,
          order_type: 'MARKET',
          quantity,
        }
      });
      await get().fetchAll();
      return res.data;
    } catch (err) {
      console.error('Failed to execute trade:', err);
      set({ error: 'Failed to execute trade' });
      return null;
    }
  },

  setStrategyId: (id: number) => set({ strategyId: id }),

  clearError: () => set({ error: null }),
}));
