import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import AppShell from '../components/layout/AppShell';
import TopBar from '../components/layout/TopBar';
import NavTabs from '../components/layout/NavTabs';
import { Strategy, StrategyMetrics } from '../types/trading';

const TABS = [
  { label: 'Terminal', href: '/' },
  { label: 'Strategies', href: '/strategies' },
  { label: 'Orders', href: '/orders' },
  { label: 'Settings', href: '/settings' },
];

export default function StrategyDetailPage() {
  const { key } = useParams<{ key: string }>();
  const [strategy, setStrategy] = useState<Strategy | null>(null);
  const [metrics, setMetrics] = useState<StrategyMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!key) return;

    Promise.all([
      fetch(`/api/strategies/key/${encodeURIComponent(key)}`).then(r => {
        if (!r.ok) throw new Error('Strategy not found');
        return r.json();
      }),
      fetch(`/api/strategies/key/${encodeURIComponent(key)}/metrics`).then(r => r.json()),
    ])
      .then(([strat, met]) => {
        setStrategy(strat);
        setMetrics(met);
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [key]);

  return (
    <AppShell>
      <TopBar />
      <NavTabs tabs={TABS} active="/strategies" />
      <main style={{ padding: '1.5rem', maxWidth: '1200px', margin: '0 auto' }}>
        <h1 style={{ marginBottom: '1.5rem' }}>
          {strategy ? `${strategy.name} (${strategy.key})` : 'Strategy'}
        </h1>

        {error && (
          <div style={{
            background: '#7f1d1d',
            color: '#fca5a5',
            padding: '1rem',
            borderRadius: '8px',
            marginBottom: '1rem',
          }}>
            {error}
          </div>
        )}

        {loading && (
          <div style={{ color: '#94a3b8' }}>Loading…</div>
        )}

        {strategy && metrics && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '1rem',
          }}>
            <MetricCard label="Win Rate" value={`${(metrics.win_rate * 100).toFixed(1)}%`} />
            <MetricCard label="Profit Factor" value={metrics.profit_factor.toFixed(2)} />
            <MetricCard label="Max Drawdown" value={`${metrics.max_drawdown_pct.toFixed(1)}%`} />
            <MetricCard label="Sharpe" value={metrics.intraday_sharpe.toFixed(2)} />
            <MetricCard label="Trades" value={metrics.trade_count.toString()} />
            <MetricCard label="Avg Hold" value={`${metrics.avg_hold_time_seconds.toFixed(0)}s`} />
          </div>
        )}
      </main>
    </AppShell>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      background: '#1e293b',
      padding: '1rem',
      borderRadius: '8px',
      border: '1px solid #334155',
    }}>
      <div style={{ color: '#94a3b8', fontSize: '0.875rem', marginBottom: '0.5rem' }}>{label}</div>
      <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{value}</div>
    </div>
  );
}
