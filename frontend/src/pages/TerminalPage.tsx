import { useEffect, useState } from 'react';
import { useStore } from '../store';
import { useMarketStore } from '../store/marketSlice';
import { usePortfolioStore } from '../store/portfolioSlice';
import AppShell from '../components/layout/AppShell';
import TopBar from '../components/layout/TopBar';
import NavTabs from '../components/layout/NavTabs';
import TickerStrip from '../components/layout/TickerStrip';
import CandleChart from '../components/market/CandleChart';
import { Candle } from '../types/market';
import { PortfolioItem } from '../store/portfolioSlice';

const TABS = [
  { label: 'Terminal', href: '/' },
  { label: 'Strategies', href: '/strategies' },
  { label: 'Orders', href: '/orders' },
  { label: 'Settings', href: '/settings' },
];

export default function TerminalPage() {
  const { fetchAll, loading } = useStore();
  const { latestPrices } = useMarketStore();

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const tickers = Object.entries(latestPrices).map(([sym, price]) => ({
    symbol: sym,
    price,
  }));

  const selectedCandles: Candle[] = [];

  return (
    <AppShell>
      <TopBar />
      <NavTabs tabs={TABS} active="/" />
      <TickerStrip tickers={tickers} />
      <main style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(12, 1fr)',
        gap: '1rem',
        padding: '1.5rem',
        maxWidth: '1600px',
        margin: '0 auto',
      }}>
        <section style={{ gridColumn: 'span 12', display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: '1rem' }}>
          <div style={{ gridColumn: 'span 4' }}>
            <PricePanel />
          </div>
          <div style={{ gridColumn: 'span 4' }}>
            <PortfolioPanel />
          </div>
          <div style={{ gridColumn: 'span 4' }}>
            <TradePanel />
          </div>
        </section>
        <section style={{ gridColumn: 'span 12' }}>
          <CandleChart candles={selectedCandles} />
        </section>
      </main>
      {loading && (
        <div style={{
          position: 'fixed',
          bottom: '1rem',
          right: '1rem',
          color: '#94a3b8',
          fontSize: '0.875rem',
        }}>
          Loading…
        </div>
      )}
    </AppShell>
  );
}

function PricePanel() {
  const { prices, fetchPrices } = useMarketStore();
  const [filter, setFilter] = useState<string>('ALL');

  useEffect(() => {
    fetchPrices();
    const interval = setInterval(fetchPrices, 5000);
    return () => clearInterval(interval);
  }, [fetchPrices]);

  const filtered = filter === 'ALL' ? prices : prices.filter(p => p.symbol === filter);

  return (
    <div style={{ background: '#1e293b', borderRadius: '8px', overflow: 'auto' }}>
      <div style={{ display: 'flex', gap: '0.5rem', padding: '0.75rem', borderBottom: '1px solid #334155' }}>
        {['ALL', 'BTC', 'ETH', 'SOL'].map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{
            background: filter === f ? '#38bdf8' : '#0f172a',
            color: filter === f ? '#0f172a' : '#cbd5e1',
            padding: '0.25rem 0.75rem',
            borderRadius: '4px',
            border: 'none',
            fontSize: '0.875rem',
            cursor: 'pointer',
          }}>{f}</button>
        ))}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr style={{ background: '#2d3748' }}>
          <th style={{ padding: '0.75rem', textAlign: 'left' }}>Symbol</th>
          <th style={{ padding: '0.75rem', textAlign: 'right' }}>Price</th>
          <th style={{ padding: '0.75rem', textAlign: 'right' }}>Time</th>
        </tr></thead>
        <tbody>
          {filtered.map(p => (
            <tr key={p.id} style={{ borderBottom: '1px solid #334155' }}>
              <td style={{ padding: '0.75rem' }}>{p.symbol}</td>
              <td style={{ padding: '0.75rem', textAlign: 'right' }}>${p.price.toFixed(2)}</td>
              <td style={{ padding: '0.75rem', textAlign: 'right' }}>{new Date(p.timestamp).toLocaleTimeString()}</td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr><td colSpan={3} style={{ padding: '1rem', textAlign: 'center', color: '#64748b' }}>No price data</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function PortfolioPanel() {
  const { portfolio, fetchPortfolio } = usePortfolioStore();

  useEffect(() => {
    fetchPortfolio();
    const interval = setInterval(fetchPortfolio, 5000);
    return () => clearInterval(interval);
  }, [fetchPortfolio]);

  const positions = portfolio.filter((p: PortfolioItem) => Number(p.balance) > 0 || Number(p.quantity) > 0);
  const totalUSD = positions.find((p: PortfolioItem) => p.symbol === 'USD');
  const totalCoins = positions.filter((p: PortfolioItem) => p.symbol !== 'USD');

  return (
    <div style={{ background: '#1e293b', borderRadius: '8px', overflow: 'auto' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '1rem', padding: '0.75rem', borderBottom: '1px solid #334155' }}>
        <div>
          <div style={{ color: '#94a3b8', fontSize: '0.875rem' }}>Cash (USD)</div>
          <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#fbbf24' }}>
            ${totalUSD?.balance.toFixed(2) || '0.00'}
          </div>
        </div>
        <div>
          <div style={{ color: '#94a3b8', fontSize: '0.875rem' }}>Assets</div>
          {totalCoins.map((p: PortfolioItem) => (
            <div key={p.symbol} style={{ fontSize: '0.875rem' }}>
              {p.symbol}: {p.quantity.toFixed(4)}
            </div>
          ))}
        </div>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr style={{ background: '#2d3748' }}>
          <th style={{ padding: '0.75rem', textAlign: 'left' }}>Symbol</th>
          <th style={{ padding: '0.75rem', textAlign: 'right' }}>Balance</th>
          <th style={{ padding: '0.75rem', textAlign: 'right' }}>Quantity</th>
          <th style={{ padding: '0.75rem', textAlign: 'right' }}>Cost Basis</th>
        </tr></thead>
        <tbody>
          {positions.map((p: PortfolioItem) => (
            <tr key={p.symbol} style={{ borderBottom: '1px solid #334155' }}>
              <td style={{ padding: '0.75rem' }}>{p.symbol}</td>
              <td style={{ padding: '0.75rem', textAlign: 'right' }}>${p.balance.toFixed(2)}</td>
              <td style={{ padding: '0.75rem', textAlign: 'right' }}>{p.quantity.toFixed(4)}</td>
              <td style={{ padding: '0.75rem', textAlign: 'right' }}>${p.cost_basis.toFixed(2)}</td>
            </tr>
          ))}
          {positions.length === 0 && (
            <tr><td colSpan={4} style={{ padding: '1rem', textAlign: 'center', color: '#64748b' }}>No positions</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function TradePanel() {
  const { executeTrade, loading, error, clearError } = useStore();
  const [symbol, setSymbol] = useState('BTC');
  const [type, setType] = useState<'BUY' | 'SELL'>('BUY');
  const [quantity, setQuantity] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const qty = Number(quantity);
    if (!qty || qty <= 0) {
      setResult('Please enter a valid quantity');
      return;
    }
    setSubmitting(true);
    setResult(null);
    const res = await executeTrade(type, symbol, qty);
    setSubmitting(false);
    if (res) {
      setResult(`${res.type} ${res.quantity} ${res.symbol} @ $${res.price.toFixed(2)}`);
      setQuantity('');
    } else {
      setResult('Trade failed — see error banner');
    }
  };

  return (
    <div style={{ background: '#1e293b', padding: '1.5rem', borderRadius: '8px' }}>
      <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem' }}>Execute Trade</h3>
      {error && (
        <div style={{ background: '#7f1d1d', color: '#fca5a5', padding: '0.75rem', borderRadius: '8px', marginBottom: '1rem' }}>
          {error}
          <button onClick={clearError} style={{ background: 'transparent', border: 'none', color: '#fca5a5', cursor: 'pointer', float: 'right' }}>✕</button>
        </div>
      )}
      {result && (
        <div style={{ background: '#14532d', color: '#86efac', padding: '0.75rem', borderRadius: '8px', marginBottom: '1rem' }}>
          {result}
        </div>
      )}
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          <span style={{ color: '#94a3b8', fontSize: '0.875rem' }}>Symbol</span>
          <select value={symbol} onChange={e => setSymbol(e.target.value)} style={{
            background: '#0f172a', color: '#e2e8f0', border: '1px solid #334155',
            padding: '0.5rem', borderRadius: '4px',
          }}>
            {['BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'DOGE', 'AVAX', 'LINK'].map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {(['BUY', 'SELL'] as const).map(t => (
            <button key={t} type="button" onClick={() => setType(t)} style={{
              flex: 1, padding: '0.5rem', borderRadius: '4px', border: 'none',
              background: type === t ? (t === 'BUY' ? '#16a34a' : '#dc2626') : '#334155',
              color: type === t ? '#fff' : '#94a3b8', fontWeight: 'bold', cursor: 'pointer',
            }}>{t}</button>
          ))}
        </div>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          <span style={{ color: '#94a3b8', fontSize: '0.875rem' }}>Quantity</span>
          <input type="number" step="0.0001" min="0" value={quantity} onChange={e => setQuantity(e.target.value)} placeholder="0.00" style={{
            background: '#0f172a', color: '#e2e8f0', border: '1px solid #334155',
            padding: '0.5rem', borderRadius: '4px',
          }} />
        </label>
        <button type="submit" disabled={submitting || loading} style={{
          padding: '0.75rem', borderRadius: '4px', border: 'none',
          background: submitting || loading ? '#475569' : '#38bdf8',
          color: '#0f172a', fontWeight: 'bold', cursor: submitting || loading ? 'not-allowed' : 'pointer',
        }}>
          {submitting ? 'Submitting…' : `Execute ${type}`}
        </button>
      </form>
    </div>
  );
}
