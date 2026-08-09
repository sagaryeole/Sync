import { useEffect, useState } from 'react';
import { useStore } from '../store';

export default function Dashboard() {
  const { latestPrices, signals, trades, loading, error, fetchAll, clearError } = useStore();
  const [showError, setShowError] = useState(true);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 5000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  // Reset dismiss flag when a new error arrives
  useEffect(() => { setShowError(true); }, [error]);

  return (
    <div>
      <h2>Dashboard</h2>

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
          <div style={{ color: '#94a3b8', fontSize: '0.875rem' }}>Current Prices</div>
          {Object.entries(latestPrices).map(([symbol, price]) => (
            <div key={symbol} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
              <span>{symbol}</span>
              <span>${price.toFixed(2)}</span>
            </div>
          ))}
          {Object.keys(latestPrices).length === 0 && !loading && (
            <div style={{ color: '#64748b', fontSize: '0.875rem' }}>No price data</div>
          )}
        </div>
        <div style={{ background: '#1e293b', padding: '1rem', borderRadius: '8px' }}>
          <div style={{ color: '#94a3b8', fontSize: '0.875rem' }}>Signals</div>
          {Object.entries(signals).map(([symbol, signal]) => (
            <div key={symbol} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
              <span>{symbol}</span>
              <span style={{ color: signal === 'BUY' ? '#4ade80' : signal === 'SELL' ? '#f87171' : '#94a3b8' }}>
                {signal || '—'}
              </span>
            </div>
          ))}
        </div>
        <div style={{ background: '#1e293b', padding: '1rem', borderRadius: '8px' }}>
          <div style={{ color: '#94a3b8', fontSize: '0.875rem' }}>Recent Trades</div>
          {trades.slice(0, 5).map(t => (
            <div key={t.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.875rem' }}>
              <span>{t.type}: {t.symbol}</span>
              <span>${t.price.toFixed(2)}x{t.quantity.toFixed(2)}</span>
            </div>
          ))}
          {trades.length === 0 && !loading && (
            <div style={{ color: '#64748b', fontSize: '0.875rem' }}>No trades yet</div>
          )}
        </div>
      </div>
    </div>
  );
}
