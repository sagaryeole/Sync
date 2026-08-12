import { useEffect, useState, useMemo } from 'react';
import { useStore } from '../store';
import { useMarketStore } from '../store/marketSlice';
import { usePortfolioStore } from '../store/portfolioSlice';
import AppShell from '../components/layout/AppShell';
import TopBar from '../components/layout/TopBar';
import NavTabs from '../components/layout/NavTabs';
import TickerStrip from '../components/layout/TickerStrip';
import CandleChart from '../components/market/CandleChart';
import ConnectionPill from '../components/layout/ConnectionPill';
import Panel from '../components/common/Panel';
import { Candle } from '../types/market';
import { useWebSocket } from '../hooks/useWebSocket';
import { fmtUsd, fmtQty, fmtTime, signClass } from '../lib/format';

const TABS = [
  { label: 'Terminal', href: '/' },
  { label: 'Strategies', href: '/strategies' },
  { label: 'Orders', href: '/orders' },
  { label: 'Journal', href: '/journal' },
  { label: 'Settings', href: '/settings' },
];

const SYMBOLS = ['BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'DOGE', 'AVAX', 'LINK'];
const CHART_SYMBOL = 'BTC';

const TH = 'px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-400';
const TD = 'px-3 py-2 text-sm';

export default function TerminalPage() {
  const { fetchAll, loading, strategies, strategyId, setStrategyId } = useStore();
  const { latestPrices, fetchPrices } = useMarketStore();
  const { fetchPortfolio } = usePortfolioStore();
  const [selectedCandles, setSelectedCandles] = useState<Candle[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState(CHART_SYMBOL);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  useEffect(() => {
    if (strategyId) fetchPortfolio(strategyId);
    const interval = setInterval(() => {
      if (strategyId) fetchPortfolio(strategyId);
    }, 5000);
    return () => clearInterval(interval);
  }, [strategyId, fetchPortfolio]);

  useEffect(() => {
    const interval = setInterval(fetchPrices, 5000);
    return () => clearInterval(interval);
  }, [fetchPrices]);

  useEffect(() => {
    let cancelled = false;
    async function loadCandles() {
      try {
        const res = await fetch(
          `/api/candles?symbol=${encodeURIComponent(selectedSymbol)}&interval=1m&limit=200`,
        );
        if (!cancelled && res.ok) {
          const data = await res.json();
          if (Array.isArray(data)) setSelectedCandles(data);
        }
      } catch {
        // Chart history is non-critical; the live WS candle stream still updates.
      }
    }
    loadCandles();
    const interval = setInterval(loadCandles, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [selectedSymbol]);

  const tickers = useMemo(
    () => Object.entries(latestPrices).map(([symbol, price]) => ({ symbol, price })),
    [latestPrices],
  );

  // Feed status is handled centrally in useWebSocket -> marketSlice, so both
  // this page and TopBar render the same value instead of disagreeing.
  const wsTopics = useMemo(() => {
    const topics = ['ticks', 'feed'];
    if (selectedSymbol) topics.push(`candles:${selectedSymbol}:1m`);
    return topics;
  }, [selectedSymbol]);

  useWebSocket(wsTopics);

  return (
    <AppShell>
      <TopBar />
      <NavTabs tabs={TABS} active="/" />
      <TickerStrip tickers={tickers} />

      <main className="mx-auto w-full max-w-[1600px] p-6">
        {/* Controls */}
        <div className="mb-4 flex flex-wrap items-center gap-4">
          <div className="flex flex-wrap gap-1.5">
            {SYMBOLS.map((sym) => (
              <button
                key={sym}
                onClick={() => setSelectedSymbol(sym)}
                aria-pressed={selectedSymbol === sym}
                className={`rounded px-3 py-1 text-sm transition-colors ${
                  selectedSymbol === sym
                    ? 'bg-sky-400 font-semibold text-slate-950'
                    : 'bg-slate-950 text-slate-300 hover:bg-slate-800'
                }`}
              >
                {sym}
              </button>
            ))}
          </div>

          {strategies.length > 0 && (
            <label className="flex items-center gap-2 text-sm text-slate-400">
              Strategy:
              <select
                value={strategyId || ''}
                onChange={(e) => setStrategyId(Number(e.target.value))}
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-200 focus:border-slate-500 focus:outline-none"
              >
                {strategies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.key})
                  </option>
                ))}
              </select>
            </label>
          )}

          <div className="ml-auto">
            <ConnectionPill />
          </div>
        </div>

        {/* Row 1 */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <PricePanel className="lg:col-span-4" />
          <PortfolioPanel strategyId={strategyId} className="lg:col-span-5" />
          <TradePanel strategyId={strategyId} className="lg:col-span-3" />
        </div>

        {/* Row 2 — chart */}
        <div className="mt-4">
          <Panel title={`${selectedSymbol} · 1m`}>
            <CandleChart candles={selectedCandles} />
          </Panel>
        </div>
      </main>

      {loading && (
        <div className="fixed bottom-4 right-4 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-400 shadow-lg">
          Loading…
        </div>
      )}
    </AppShell>
  );
}

function PricePanel({ className = '' }: { className?: string }) {
  const { prices } = useMarketStore();
  const [filter, setFilter] = useState<string>('ALL');

  const filtered = filter === 'ALL' ? prices : prices.filter((p) => p.symbol === filter);

  return (
    <Panel
      title="Prices"
      className={className}
      flush
      actions={
        <div className="flex gap-1">
          {['ALL', 'BTC', 'ETH', 'SOL'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              aria-pressed={filter === f}
              className={`rounded px-2 py-0.5 text-xs transition-colors ${
                filter === f
                  ? 'bg-sky-400 font-semibold text-slate-950'
                  : 'bg-slate-950 text-slate-400 hover:bg-slate-800'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      }
    >
      <table className="w-full border-collapse">
        <thead className="sticky top-0 bg-slate-800/80 backdrop-blur">
          <tr>
            <th className={TH}>Symbol</th>
            <th className={`${TH} text-right`}>Price</th>
            <th className={`${TH} text-right`}>Time</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((p) => (
            <tr key={p.id} className="border-b border-slate-800/60 last:border-0">
              <td className={`${TD} font-medium text-slate-200`}>{p.symbol}</td>
              <td className={`${TD} text-right tabular-nums`}>{fmtUsd(p.price)}</td>
              <td className={`${TD} text-right text-slate-500`}>{fmtTime(p.timestamp)}</td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={3} className="px-3 py-8 text-center text-sm text-slate-500">
                No price data
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function PortfolioPanel({
  strategyId,
  className = '',
}: {
  strategyId: number | null;
  className?: string;
}) {
  const { positions, account, fetchPortfolio } = usePortfolioStore();

  useEffect(() => {
    if (strategyId) fetchPortfolio(strategyId);
  }, [strategyId, fetchPortfolio]);

  const openPositions = positions.filter((p) => Number(p.quantity) > 0);

  return (
    <Panel title="Portfolio" className={className} flush>
      <div className="grid grid-cols-2 gap-4 border-b border-slate-800 p-4">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">Cash (USD)</div>
          <div className="text-xl font-bold tabular-nums text-amber-400">
            {fmtUsd(account?.cash)}
          </div>
          <div className={`mt-0.5 text-xs tabular-nums ${signClass(account?.realized_pnl)}`}>
            Realised P&amp;L: {fmtUsd(account?.realized_pnl)}
          </div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">Open Positions</div>
          <div className="text-xl font-bold tabular-nums text-slate-100">
            {openPositions.length}
          </div>
          {account?.is_halted && (
            <div className="mt-0.5 text-xs text-rose-400">
              HALTED{account.halt_reason ? ` · ${account.halt_reason}` : ''}
            </div>
          )}
        </div>
      </div>

      <table className="w-full border-collapse">
        <thead className="bg-slate-800/50">
          <tr>
            <th className={TH}>Symbol</th>
            <th className={`${TH} text-right`}>Qty</th>
            <th className={`${TH} text-right`}>Avg Entry</th>
            <th className={`${TH} text-right`}>SL</th>
            <th className={`${TH} text-right`}>TP</th>
          </tr>
        </thead>
        <tbody>
          {openPositions.map((p) => (
            <tr key={p.symbol} className="border-b border-slate-800/60 last:border-0">
              <td className={`${TD} font-medium text-slate-200`}>{p.symbol}</td>
              <td className={`${TD} text-right tabular-nums`}>{fmtQty(p.quantity, 4)}</td>
              <td className={`${TD} text-right tabular-nums`}>{fmtUsd(p.avg_entry_price)}</td>
              <td className={`${TD} text-right tabular-nums text-rose-400/80`}>
                {fmtUsd(p.stop_loss_price)}
              </td>
              <td className={`${TD} text-right tabular-nums text-emerald-400/80`}>
                {fmtUsd(p.take_profit_price)}
              </td>
            </tr>
          ))}
          {openPositions.length === 0 && (
            <tr>
              <td colSpan={5} className="px-3 py-8 text-center text-sm text-slate-500">
                No open positions
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function TradePanel({
  strategyId,
  className = '',
}: {
  strategyId: number | null;
  className?: string;
}) {
  const { executeTrade, loading, error, clearError } = useStore();
  const [symbol, setSymbol] = useState('BTC');
  const [type, setType] = useState<'BUY' | 'SELL'>('BUY');
  const [quantity, setQuantity] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const disabled = submitting || loading || !strategyId;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const qty = Number(quantity);
    if (!Number.isFinite(qty) || qty <= 0) {
      setResult('Enter a valid quantity');
      return;
    }
    if (!strategyId) {
      setResult('No strategy selected');
      return;
    }
    setSubmitting(true);
    setResult(null);
    const res = await executeTrade(type, symbol, qty, strategyId);
    setSubmitting(false);
    if (res) {
      setResult(`${res.type} ${fmtQty(res.quantity, 4)} ${res.symbol} @ ${fmtUsd(res.price)}`);
      setQuantity('');
    } else {
      setResult('Trade failed — see error banner');
    }
  };

  return (
    <Panel title="Execute Trade" className={className}>
      {error && (
        <div className="mb-3 flex items-start justify-between gap-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          <span>{error}</span>
          <button onClick={clearError} aria-label="Dismiss error" className="text-rose-300">
            ✕
          </button>
        </div>
      )}
      {result && (
        <div className="mb-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {result}
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1.5">
          <span className="text-xs uppercase tracking-wide text-slate-400">Symbol</span>
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-2 text-sm text-slate-200 focus:border-slate-500 focus:outline-none"
          >
            {SYMBOLS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        <div className="flex gap-2">
          {(['BUY', 'SELL'] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setType(t)}
              aria-pressed={type === t}
              className={`flex-1 rounded py-2 text-sm font-bold transition-colors ${
                type === t
                  ? t === 'BUY'
                    ? 'bg-emerald-600 text-white'
                    : 'bg-rose-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs uppercase tracking-wide text-slate-400">Quantity</span>
          <input
            type="number"
            step="0.0001"
            min="0"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            placeholder="0.00"
            className="rounded border border-slate-700 bg-slate-950 px-2 py-2 text-sm tabular-nums text-slate-200 placeholder:text-slate-600 focus:border-slate-500 focus:outline-none"
          />
        </label>

        <button
          type="submit"
          disabled={disabled}
          className="rounded bg-sky-400 py-2.5 text-sm font-bold text-slate-950 transition-colors hover:bg-sky-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
        >
          {submitting ? 'Submitting…' : `Execute ${type}`}
        </button>
      </form>
    </Panel>
  );
}
