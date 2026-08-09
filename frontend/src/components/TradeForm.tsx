import { useState } from 'react';
import { useStore } from '../store';

const SYMBOLS = ['BTC', 'ETH', 'SOL'];

export default function TradeForm() {
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
    <div>
      <h2>Execute Trade</h2>

      {error && (
        <div style={{
          background: '#7f1d1d', color: '#fca5a5', padding: '0.75rem 1rem',
          borderRadius: '8px', marginBottom: '1rem', display: 'flex',
          justifyContent: 'space-between', alignItems: 'center'
        }}>
          <span>{error}</span>
          <button
            onClick={clearError}
            style={{ background: 'transparent', border: 'none', color: '#fca5a5', cursor: 'pointer' }}
          >
            ✕
          </button>
        </div>
      )}

      {result && (
        <div style={{
          background: '#14532d', color: '#86efac', padding: '0.75rem 1rem',
          borderRadius: '8px', marginBottom: '1rem'
        }}>
          {result}
        </div>
      )}

      <form onSubmit={handleSubmit} style={{
        background: '#1e293b', padding: '1.5rem', borderRadius: '8px',
        display: 'flex', flexDirection: 'column', gap: '1rem', maxWidth: '400px'
      }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          <span style={{ color: '#94a3b8', fontSize: '0.875rem' }}>Symbol</span>
          <select
            value={symbol}
            onChange={e => setSymbol(e.target.value)}
            style={{
              background: '#0f172a', color: '#e2e8f0', border: '1px solid #334155',
              padding: '0.5rem', borderRadius: '4px'
            }}
          >
            {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>

        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {(['BUY', 'SELL'] as const).map(t => (
            <button
              key={t}
              type="button"
              onClick={() => setType(t)}
              style={{
                flex: 1, padding: '0.5rem', borderRadius: '4px', border: 'none',
                background: type === t ? (t === 'BUY' ? '#16a34a' : '#dc2626') : '#334155',
                color: type === t ? '#fff' : '#94a3b8', fontWeight: 'bold', cursor: 'pointer'
              }}
            >
              {t}
            </button>
          ))}
        </div>

        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          <span style={{ color: '#94a3b8', fontSize: '0.875rem' }}>Quantity</span>
          <input
            type="number"
            step="0.0001"
            min="0"
            value={quantity}
            onChange={e => setQuantity(e.target.value)}
            placeholder="0.00"
            style={{
              background: '#0f172a', color: '#e2e8f0', border: '1px solid #334155',
              padding: '0.5rem', borderRadius: '4px'
            }}
          />
        </label>

        <button
          type="submit"
          disabled={submitting || loading}
          style={{
            padding: '0.75rem', borderRadius: '4px', border: 'none',
            background: submitting || loading ? '#475569' : '#38bdf8',
            color: '#0f172a', fontWeight: 'bold', cursor: submitting || loading ? 'not-allowed' : 'pointer'
          }}
        >
          {submitting ? 'Submitting…' : `Execute ${type}`}
        </button>
      </form>
    </div>
  );
}
