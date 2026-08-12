import { create } from 'zustand';
import api from '../api';

interface PriceTicker {
  id: number;
  symbol: string;
  price: number;
  timestamp: string;
}

export type FeedStatus = 'connected' | 'disconnected' | 'degraded';

interface MarketState {
  prices: PriceTicker[];
  latestPrices: Record<string, number>;
  /** Live feed status, fed by the WS `feed` topic. Single source of truth —
   *  TopBar and the terminal both read this. Previously TopBar rendered a
   *  ConnectionPill with no props, so it was permanently stuck on the
   *  'disconnected' default and contradicted the terminal's own indicator. */
  feedStatus: FeedStatus;
  feedProvider: string | null;
  setFeedStatus: (status: FeedStatus, provider?: string | null) => void;
  setLatestPrices: (updater: Record<string, number> | ((prev: Record<string, number>) => Record<string, number>)) => void;
  fetchPrices: () => Promise<void>;
}

export const useMarketStore = create<MarketState>((set) => ({
  prices: [],
  latestPrices: {},
  feedStatus: 'disconnected',
  feedProvider: null,
  setFeedStatus: (status, provider) =>
    set((state) => ({
      feedStatus: status,
      feedProvider: provider === undefined ? state.feedProvider : provider,
    })),
  setLatestPrices: (updater) => set((state) => ({
    latestPrices: typeof updater === 'function' ? (updater as (prev: Record<string, number>) => Record<string, number>)(state.latestPrices) : updater,
  })),
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
      set((state) => ({
        prices: data,
        latestPrices: data.length > 0 ? { ...state.latestPrices, ...latest } : {},
      }));
    } catch (err) {
      console.error('Failed to fetch prices:', err);
    }
  },
}));
