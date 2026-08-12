import { create } from 'zustand';
import api from '../api';

export interface PortfolioItem {
  symbol: string;
  balance: number;
  quantity: number;
  cost_basis: number;
}

interface PortfolioState {
  portfolio: PortfolioItem[];
  fetchPortfolio: () => Promise<void>;
}

export const usePortfolioStore = create<PortfolioState>((set) => ({
  portfolio: [],
  fetchPortfolio: async () => {
    try {
      const res = await api.get<PortfolioItem[]>('/portfolio');
      const data = Array.isArray(res.data) ? res.data : [];
      set({ portfolio: data });
    } catch (err) {
      console.error('Failed to fetch portfolio:', err);
    }
  },
}));
