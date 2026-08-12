import ConnectionPill from './ConnectionPill';

export default function TopBar() {
  return (
    <header style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0.75rem 1.5rem',
      background: '#1e293b',
      borderBottom: '1px solid #334155',
    }}>
      <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>
        CryptoTrade
      </div>
      <ConnectionPill />
    </header>
  );
}
