import { Candle } from '../types/market';

type Interval = '5m' | '15m' | '1h';

const INTERVAL_MS: Record<Interval, number> = {
  '5m': 5 * 60 * 1000,
  '15m': 15 * 60 * 1000,
  '1h': 60 * 60 * 1000,
};

export function bucketCandles(candles: Candle[], interval: Interval): Candle[] {
  const bucketSize = INTERVAL_MS[interval];
  const buckets = new Map<number, Candle[]>();

  for (const c of candles) {
    const bucketKey = Math.floor(c.open_time / bucketSize) * bucketSize;
    const existing = buckets.get(bucketKey);
    if (existing) {
      existing.push(c);
    } else {
      buckets.set(bucketKey, [c]);
    }
  }

  const result: Candle[] = [];
  for (const [key, group] of Array.from(buckets.entries()).sort((a, b) => a[0] - b[0])) {
    const open = group[0].open;
    const high = Math.max(...group.map(c => c.high));
    const low = Math.min(...group.map(c => c.low));
    const close = group[group.length - 1].close;
    const volume = group.reduce((sum, c) => sum + c.volume, 0);
    const trades = group.reduce((sum, c) => sum + c.trades, 0);

    result.push({
      symbol: group[0].symbol,
      interval,
      open_time: key,
      open,
      high,
      low,
      close,
      volume,
      trades,
      source: group[0].source,
    });
  }

  return result;
}
