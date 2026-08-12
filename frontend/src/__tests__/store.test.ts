import { describe, it, expect, vi } from 'vitest';
import { useMarketStore } from '../store/marketSlice';
import { usePortfolioStore } from '../store/portfolioSlice';

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
  },
}));

import api from '../api';

describe('marketSlice', () => {
  it('fetchPrices populates latestPrices and prices', async () => {
    const mockData = [
      { id: 1, symbol: 'BTC', price: 50000, timestamp: '2024-01-01T00:00:00Z' },
      { id: 2, symbol: 'ETH', price: 3000, timestamp: '2024-01-01T00:00:00Z' },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: mockData });

    await useMarketStore.getState().fetchPrices();

    expect(useMarketStore.getState().prices).toEqual(mockData);
    expect(useMarketStore.getState().latestPrices).toEqual({ BTC: 50000, ETH: 3000 });
  });

  it('fetchPrices handles empty response', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });

    await useMarketStore.getState().fetchPrices();

    expect(useMarketStore.getState().prices).toEqual([]);
    expect(useMarketStore.getState().latestPrices).toEqual({});
  });

  it('fetchPrices handles API error gracefully', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('Network error'));

    await useMarketStore.getState().fetchPrices();

    expect(useMarketStore.getState().prices).toEqual([]);
    expect(useMarketStore.getState().latestPrices).toEqual({});
  });
});

describe('portfolioSlice', () => {
  it('fetchPortfolio populates positions and account', async () => {
    const mockPositions = [
      { id: 1, strategy_id: 1, symbol: 'BTC', quantity: 0.2, avg_entry_price: 45000, realized_pnl: 0, stop_loss_price: 44100, take_profit_price: 46800, opened_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
    ];
    const mockAccount = [
      { id: 1, strategy_id: 1, cash: 91000, realized_pnl: 0, fees_paid: 0, peak_equity: 100000, is_halted: false, halt_reason: '', updated_at: '2024-01-01T00:00:00Z' },
    ];
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url.includes('/positions')) return Promise.resolve({ data: mockPositions });
      if (url.includes('/portfolio')) return Promise.resolve({ data: mockAccount });
      return Promise.resolve({ data: null });
    });

    await usePortfolioStore.getState().fetchPortfolio(1);

    expect(usePortfolioStore.getState().positions).toEqual(mockPositions);
    expect(usePortfolioStore.getState().account).toEqual(mockAccount[0]);
  });

  it('fetchPortfolio handles null strategyId', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });

    await usePortfolioStore.getState().fetchPortfolio(null);

    expect(usePortfolioStore.getState().positions).toEqual([]);
    expect(usePortfolioStore.getState().account).toBeNull();
  });

  it('fetchPortfolio handles non-array response', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url.includes('/positions')) return Promise.resolve({ data: {} });
      if (url.includes('/portfolio')) return Promise.resolve({ data: [] });
      return Promise.resolve({ data: null });
    });

    await usePortfolioStore.getState().fetchPortfolio(1);

    expect(usePortfolioStore.getState().positions).toEqual([]);
    expect(usePortfolioStore.getState().account).toBeNull();
  });
});
