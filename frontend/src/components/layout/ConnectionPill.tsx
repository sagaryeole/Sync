type Status = 'connected' | 'disconnected' | 'degraded';

interface Props {
  status?: Status;
  label?: string;
}

const COLORS: Record<Status, string> = {
  connected: '#4ade80',
  disconnected: '#f87171',
  degraded: '#fbbf24',
};

export default function ConnectionPill({ status = 'disconnected', label }: Props) {
  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.5rem',
      padding: '0.25rem 0.75rem',
      borderRadius: '9999px',
      border: '1px solid #334155',
      background: '#1e293b',
      fontSize: '0.75rem',
      fontWeight: 500,
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
    }}>
      <span style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: COLORS[status],
      }} />
      {label || status}
    </div>
  );
}
