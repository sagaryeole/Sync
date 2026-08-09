import { useEffect, useState } from 'react';
import { useStore } from '../store';

export default function Portfolio() {
  const { portfolio, loading, error, fetchPortfolio, clearError } = useStore();
  const [showError, setShowError] = useState(true);

  useEffect(() => {
    fetchPortfolio();
    const interval = setInterval(fetchPortfolio, 5000);
    return () => clearInterval(interval);
  }, [fetchPortfolio]);

  useEffect(() => { setShowError(true); }, [error]);

  const positions = portfolio.filter(
    p => Number(p.balance) > 0 || Number(p.quantity) > 0
  );
  const totalUSD = positions.find(p => p.symbol === 'USD');
  const totalCoins = positions.filter(p => p.symbol !== 'USD');

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

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
        <div style={{ background: '#1e293b', padding: '1rem', borderRadius: '8px' }}>
          <div style={{ color: '#94a3b8', fontSize: '0.875rem', marginBottom: '0.5rem' }}>Cash (USD)</div>
          <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#fbbf24' }}>${totalUSD?.balance.toFixed(2) || '0.00'}</div>
        </div>
        <div style={{ background: '#1e293b', padding: '1rem', borderRadius: '8px' }}>
          <div style={{ color: '#94a3b8', fontSize: '0.875rem', marginBottom: '0.5rem' }}>Assets</div>
          {totalCoins.map(p => (
            <div key={p.symbol}>
              {p.symbol}: {p.quantity.toFixed(4)} {p.symbol === 'USD' ? '' : 'coins'}
            </div>
          ))}
        </div>
      </div>
      <div style={{ background: '#1e293b', borderRadius: '8px', overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#2d3748' }}>
              <th style={{ padding: '0.75rem', textAlign: 'left' }}>Symbol</th>
              <th style={{ padding: '0.75rem', textAlign: 'right' }}>Balance</th>
              <th style={{ padding: '0.75rem', textAlign: 'right' }}>Quantity</th>
              <th style={{ padding: '0.75rem', textAlign: 'right' }}>Cost Basis</th>
            </tr>
          </thead>
          <tbody>
            {positions.map(p => (
              <tr key={p.symbol} style={{ borderBottom: '1px solid #334155' }}>
                <td style={{ padding: '0.75rem' }}>{p.symbol}</td>
                <td style={{ padding: '0.75rem', textAlign: 'right' }}>${p.balance.toFixed(2)}</td>
                <td style={{ padding: '0.75rem', textAlign: 'right' }}>{p.quantity.toFixed(4)}</td>
                <td style={{ padding: '0.75rem', textAlign: 'right' }}>${p.cost_basis.toFixed(2)}</td>
              </tr>
            ))}
            {positions.length === 0 && !loading && (
              <tr>
                <td colSpan={4} style={{ padding: '1rem', textAlign: 'center', color: '#64748b' }}>
                  No positions
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
