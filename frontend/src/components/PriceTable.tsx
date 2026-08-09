import { useEffect, useState } from 'react';
import { useStore } from '../store';

export default function PriceTable() {
  const { prices, loading, error, fetchPrices, clearError } = useStore();
  const [filter, setFilter] = useState<string>('ALL');
  const [showError, setShowError] = useState(true);

  useEffect(() => {
    fetchPrices();
    const interval = setInterval(fetchPrices, 5000);
    return () => clearInterval(interval);
  }, [fetchPrices]);

  useEffect(() => { setShowError(true); }, [error]);

  const filtered = filter === 'ALL' ? prices : prices.filter(p => p.symbol === filter);

  return (
    <div>
      {loading && (
        <div style={{ color: '#94a3b8', marginBottom: '1rem' }}>Loading…</div>
      )}

      {error && showError && (
        <div style={{
          background: '#7f1d1d', color: '#fca5a5', padding: '0.75rem 1rem',
          borderRadius: '8px', marginBottom: '1rem', display: 'flex',
          justifyContent: 'space-between', alignItems: 'center'
        }}>
          <span>{error}</span>
          <button
            onClick={() => { clearError(); setShowError(false); }}
            style={{ background: 'transparent', border: 'none', color: '#fca5a5', cursor: 'pointer' }}
          >
            ✕
          </button>
        </div>
      )}

      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
        {['ALL', 'BTC', 'ETH', 'SOL'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              background: filter === f ? '#38bdf8' : '#1e293b',
              color: filter === f ? '#0f172a' : '#cbd5e1',
              padding: '0.5rem 1rem',
              borderRadius: '4px',
              border: 'none',
              fontSize: '0.875rem'
            }}
          >
            {f}
          </button>
        ))}
      </div>
      <div style={{ background: '#1e293b', borderRadius: '8px', overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#2d3748' }}>
              <th style={{ padding: '0.75rem', textAlign: 'left' }}>Symbol</th>
              <th style={{ padding: '0.75rem', textAlign: 'right' }}>Price</th>
              <th style={{ padding: '0.75rem', textAlign: 'right' }}>Time</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(p => (
              <tr key={p.id} style={{ borderBottom: '1px solid #334155' }}>
                <td style={{ padding: '0.75rem' }}>{p.symbol}</td>
                <td style={{ padding: '0.75rem', textAlign: 'right' }}>${p.price.toFixed(2)}</td>
                <td style={{ padding: '0.75rem', textAlign: 'right' }}>{new Date(p.timestamp).toLocaleTimeString()}</td>
              </tr>
            ))}
            {filtered.length === 0 && !loading && (
              <tr>
                <td colSpan={3} style={{ padding: '1rem', textAlign: 'center', color: '#64748b' }}>
                  No price data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
