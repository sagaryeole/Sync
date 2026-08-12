interface Ticker {
  symbol: string;
  price: number;
  change?: number;
}

interface Props {
  tickers: Ticker[];
}

export default function TickerStrip({ tickers }: Props) {
  return (
    <div style={{
      display: 'flex',
      gap: '0.75rem',
      padding: '0.5rem 1.5rem',
      overflowX: 'auto',
      borderBottom: '1px solid #1e293b',
    }}>
      {tickers.map(t => (
        <div
          key={t.symbol}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            padding: '0.25rem 0.75rem',
            background: '#1e293b',
            borderRadius: '9999px',
            border: '1px solid #334155',
            fontSize: '0.875rem',
            whiteSpace: 'nowrap',
          }}
        >
          <span style={{
            color: t.change === undefined ? '#cbd5e1' : t.change >= 0 ? '#4ade80' : '#f87171',
            fontWeight: 600,
          }}>
            {t.symbol}
          </span>
          <span style={{ color: '#94a3b8' }}>${t.price.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}
