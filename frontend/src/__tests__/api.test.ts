import { describe, it, expect, vi } from 'vitest';
import * as endpoints from '../api/endpoints';

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import api from '../api';

describe('api/endpoints', () => {
  describe('fetchAssets', () => {
    it('returns parsed assets', async () => {
      vi.mocked(api.get).mockResolvedValue({ data: [{ id: 1, symbol: 'BTC', name: 'Bitcoin' }] });
      const result = await endpoints.fetchAssets();
      expect(result).toEqual([{ id: 1, symbol: 'BTC', name: 'Bitcoin' }]);
    });
  });

  describe('fetchAsset', () => {
    it('encodes symbol in URL', async () => {
      vi.mocked(api.get).mockResolvedValue({ data: { id: 1, symbol: 'BTC', name: 'Bitcoin' } });
      await endpoints.fetchAsset('BTC');
      expect(api.get).toHaveBeenCalledWith('/assets/BTC');
    });
  });

  describe('fetchPrices', () => {
    it('passes params to request', async () => {
      vi.mocked(api.get).mockResolvedValue({ data: [] });
      await endpoints.fetchPrices({ asset: 'BTC', start: '2024-01-01' });
      expect(api.get).toHaveBeenCalledWith('/prices', { params: { asset: 'BTC', start: '2024-01-01' } });
    });
  });

  describe('fetchPortfolio', () => {
    it('returns parsed portfolio', async () => {
      vi.mocked(api.get).mockResolvedValue({ data: [{ symbol: 'BTC', balance: 10000, quantity: 0.2, cost_basis: 45000 }] });
      const result = await endpoints.fetchPortfolio();
      expect(result).toEqual([{ symbol: 'BTC', balance: 10000, quantity: 0.2, cost_basis: 45000 }]);
    });
  });

  describe('executeTrade', () => {
    it('sends trade payload', async () => {
      vi.mocked(api.post).mockResolvedValue({ data: { status: 'ok', type: 'BUY', symbol: 'BTC', quantity: 1, price: 50000 } });
      const result = await endpoints.executeTrade({ type: 'BUY', symbol: 'BTC', quantity: 1 });
      expect(result).toEqual({ status: 'ok', type: 'BUY', symbol: 'BTC', quantity: 1, price: 50000 });
      expect(api.post).toHaveBeenCalledWith('/trade', { type: 'BUY', symbol: 'BTC', quantity: 1 });
    });
  });

  describe('fetchTrades', () => {
    it('passes limit and offset', async () => {
      vi.mocked(api.get).mockResolvedValue({ data: [] });
      await endpoints.fetchTrades({ limit: 50, offset: 10 });
      expect(api.get).toHaveBeenCalledWith('/trades', { params: { limit: 50, offset: 10 } });
    });
  });

  describe('fetchBotSignals', () => {
    it('returns signal map', async () => {
      vi.mocked(api.get).mockResolvedValue({ data: { BTC: 'BUY', ETH: 'SELL' } });
      const result = await endpoints.fetchBotSignals();
      expect(result).toEqual({ BTC: 'BUY', ETH: 'SELL' });
    });
  });
});
