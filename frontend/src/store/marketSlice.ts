import { create } from 'zustand';
import api from '../api';

interface PriceTicker {
  id: number;
  symbol: string;
  price: number;
  timestamp: string;
}

interface MarketState {
  prices: PriceTicker[];
  latestPrices: Record<string, number>;
  fetchPrices: () => Promise<void>;
}

export const useMarketStore = create<MarketState>((set) => ({
  prices: [],
  latestPrices: {},
  fetchPrices: async () => {
    try {
      const res = await api.get<PriceTicker[]>('/prices');
      const data = Array.isArray(res.data) ? res.data : [];
      const latest: Record<string, number> = {};
      for (const p of data) {
        if (p && p.symbol && !(p.symbol in latest)) {
          latest[p.symbol] = Number(p.price);
        }
      }
      set({ prices: data, latestPrices: latest });
    } catch (err) {
      console.error('Failed to fetch prices:', err);
    }
  },
}));
