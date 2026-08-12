interface Props {
  symbol: string;
  price: number;
  change?: number;
}

export default function TickerPill({ symbol, price, change }: Props) {
  const color = change === undefined ? '#cbd5e1' : change >= 0 ? '#4ade80' : '#f87171';
  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.5rem',
      padding: '0.25rem 0.75rem',
      background: '#1e293b',
      borderRadius: '9999px',
      border: '1px solid #334155',
      fontSize: '0.875rem',
    }}>
      <span style={{ color, fontWeight: 600 }}>{symbol}</span>
      <span style={{ color: '#94a3b8' }}>${price.toFixed(2)}</span>
    </div>
  );
}
