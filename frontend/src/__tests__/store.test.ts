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
  it('fetchPortfolio populates portfolio array', async () => {
    const mockData = [
      { symbol: 'BTC', balance: 10000, quantity: 0.2, cost_basis: 45000 },
      { symbol: 'ETH', balance: 5000, quantity: 1.5, cost_basis: 2800 },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: mockData });

    await usePortfolioStore.getState().fetchPortfolio();

    expect(usePortfolioStore.getState().portfolio).toEqual(mockData);
  });

  it('fetchPortfolio handles non-array response', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: {} });

    await usePortfolioStore.getState().fetchPortfolio();

    expect(usePortfolioStore.getState().portfolio).toEqual([]);
  });
});
