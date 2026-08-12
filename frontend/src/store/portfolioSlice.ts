import { create } from 'zustand';
import api from '../api';

export interface PortfolioItem {
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

export interface AccountInfo {
  id: number;
  strategy_id: number;
  cash: number;
  realized_pnl: number;
  fees_paid: number;
  peak_equity: number;
  is_halted: boolean;
  halt_reason: string;
  updated_at: string;
}

interface PortfolioState {
  positions: PortfolioItem[];
  account: AccountInfo | null;
  fetchPortfolio: (strategyId: number | null) => Promise<void>;
}

export const usePortfolioStore = create<PortfolioState>((set) => ({
  positions: [],
  account: null,
  fetchPortfolio: async (strategyId: number | null) => {
    if (!strategyId) {
      set({ positions: [], account: null });
      return;
    }
    try {
      const [positionsRes, accountRes] = await Promise.all([
        api.get<PortfolioItem[]>(`/strategies/${strategyId}/positions`),
        api.get<AccountInfo[]>(`/strategies/${strategyId}/portfolio`),
      ]);
      const positions = Array.isArray(positionsRes.data) ? positionsRes.data : [];
      const account = Array.isArray(accountRes.data) && accountRes.data.length > 0 ? accountRes.data[0] : null;
      set({ positions, account });
    } catch (err) {
      console.error('Failed to fetch portfolio:', err);
    }
  },
}));
