import { useEffect, useState } from 'react';
import AppShell from '../components/layout/AppShell';
import TopBar from '../components/layout/TopBar';
import NavTabs from '../components/layout/NavTabs';
import { Order } from '../types/trading';

const TABS = [
  { label: 'Terminal', href: '/' },
  { label: 'Strategies', href: '/strategies' },
  { label: 'Orders', href: '/orders' },
  { label: 'Settings', href: '/settings' },
];

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState({ strategy: '', symbol: '', status: '' });

  useEffect(() => {
    const params = new URLSearchParams();
    if (filter.strategy) params.set('strategy', filter.strategy);
    if (filter.symbol) params.set('symbol', filter.symbol);
    if (filter.status) params.set('status', filter.status);

    fetch(`/api/orders?${params.toString()}`)
      .then(r => r.json())
      .then(setOrders)
      .finally(() => setLoading(false));
  }, [filter]);

  return (
    <AppShell>
      <TopBar />
      <NavTabs tabs={TABS} active="/orders" />
      <main style={{ padding: '1.5rem', maxWidth: '1400px', margin: '0 auto' }}>
        <h1 style={{ marginBottom: '1rem' }}>Orders</h1>

        <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
          <input
            placeholder="Strategy ID"
            value={filter.strategy}
            onChange={e => setFilter({ ...filter, strategy: e.target.value })}
            style={inputStyle}
          />
          <input
            placeholder="Symbol"
            value={filter.symbol}
            onChange={e => setFilter({ ...filter, symbol: e.target.value })}
            style={inputStyle}
          />
          <input
            placeholder="Status"
            value={filter.status}
            onChange={e => setFilter({ ...filter, status: e.target.value })}
            style={inputStyle}
          />
        </div>

        {loading && <div style={{ color: '#94a3b8' }}>Loading…</div>}

        <div style={{ background: '#1e293b', borderRadius: '8px', overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#2d3748' }}>
                <th style={thStyle}>ID</th>
                <th style={thStyle}>Symbol</th>
                <th style={thStyle}>Side</th>
                <th style={thStyle}>Type</th>
                <th style={thStyle}>Qty</th>
                <th style={thStyle}>Filled</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Price</th>
                <th style={thStyle}>Created</th>
              </tr>
            </thead>
            <tbody>
              {orders.map(o => (
                <tr key={o.id} style={{ borderBottom: '1px solid #334155' }}>
                  <td style={tdStyle}>{o.id}</td>
                  <td style={tdStyle}>{o.symbol}</td>
                  <td style={tdStyle}>{o.side}</td>
                  <td style={tdStyle}>{o.order_type}</td>
                  <td style={tdStyle}>{o.quantity.toFixed(4)}</td>
                  <td style={tdStyle}>{o.filled_quantity.toFixed(4)}</td>
                  <td style={tdStyle}>{o.status}</td>
                  <td style={tdStyle}>{o.filled_price.toFixed(2)}</td>
                  <td style={tdStyle}>{new Date(o.created_at).toLocaleString()}</td>
                </tr>
              ))}
              {orders.length === 0 && !loading && (
                <tr>
                  <td colSpan={9} style={{ padding: '1rem', textAlign: 'center', color: '#64748b' }}>
                    No orders
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

const inputStyle = {
  background: '#0f172a',
  color: '#e2e8f0',
  border: '1px solid #334155',
  padding: '0.5rem 0.75rem',
  borderRadius: '4px',
  fontSize: '0.875rem',
} as const;

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
