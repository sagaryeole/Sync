import { useEffect, useState } from 'react';
import AppShell from '../components/layout/AppShell';
import TopBar from '../components/layout/TopBar';
import NavTabs from '../components/layout/NavTabs';
import { Fill } from '../types/trading';

const TABS = [
  { label: 'Terminal', href: '/' },
  { label: 'Strategies', href: '/strategies' },
  { label: 'Orders', href: '/orders' },
  { label: 'Settings', href: '/settings' },
];

export default function JournalPage() {
  const [fills, setFills] = useState<Fill[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/fills?limit=100')
      .then(r => r.json())
      .then(setFills)
      .finally(() => setLoading(false));
  }, []);

  return (
    <AppShell>
      <TopBar />
      <NavTabs tabs={TABS} active="/journal" />
      <main style={{ padding: '1.5rem', maxWidth: '1400px', margin: '0 auto' }}>
        <h1 style={{ marginBottom: '1rem' }}>Trade Journal</h1>

        {loading && <div style={{ color: '#94a3b8' }}>Loading…</div>}

        <div style={{ background: '#1e293b', borderRadius: '8px', overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#2d3748' }}>
                <th style={thStyle}>Time</th>
                <th style={thStyle}>Symbol</th>
                <th style={thStyle}>Side</th>
                <th style={thStyle}>Qty</th>
                <th style={thStyle}>Price</th>
                <th style={thStyle}>Fee</th>
                <th style={thStyle}>P&L</th>
                <th style={thStyle}>Liq</th>
              </tr>
            </thead>
            <tbody>
              {fills.map(f => (
                <tr key={f.id} style={{ borderBottom: '1px solid #334155' }}>
                  <td style={tdStyle}>{new Date(f.ts).toLocaleString()}</td>
                  <td style={tdStyle}>{f.symbol}</td>
                  <td style={tdStyle}>{f.side}</td>
                  <td style={tdStyle}>{f.quantity.toFixed(4)}</td>
                  <td style={tdStyle}>{f.price.toFixed(2)}</td>
                  <td style={tdStyle}>{f.fee.toFixed(2)}</td>
                  <td style={{
                    ...tdStyle,
                    color: f.realized_pnl >= 0 ? '#4ade80' : '#f87171',
                  }}>
                    {f.realized_pnl.toFixed(2)}
                  </td>
                  <td style={tdStyle}>{f.liquidity}</td>
                </tr>
              ))}
              {fills.length === 0 && !loading && (
                <tr>
                  <td colSpan={8} style={{ padding: '1rem', textAlign: 'center', color: '#64748b' }}>
                    No fills yet
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>
    </AppShell>
  );
}

const thStyle = {
  padding: '0.75rem',
  textAlign: 'left' as const,
  color: '#94a3b8',
  fontSize: '0.875rem',
  fontWeight: 500,
} as const;

const tdStyle = {
  padding: '0.75rem',
  fontSize: '0.875rem',
} as const;
