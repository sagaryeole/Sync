import { useEffect, useState } from 'react';
import AppShell from '../components/layout/AppShell';
import TopBar from '../components/layout/TopBar';
import NavTabs from '../components/layout/NavTabs';
import ConnectionPill from '../components/layout/ConnectionPill';

const TABS = [
  { label: 'Terminal', href: '/' },
  { label: 'Strategies', href: '/strategies' },
  { label: 'Orders', href: '/orders' },
  { label: 'Settings', href: '/settings' },
];

export default function SettingsPage() {
  const [feedStatus, setFeedStatus] = useState<{ provider: string; status: string } | null>(null);
  const [providers, setProviders] = useState<string[]>([]);
  const [activeProvider, setActiveProvider] = useState('');

  useEffect(() => {
    fetch('/api/feed/status')
      .then(r => r.json())
      .then(data => {
        setFeedStatus(data);
        setProviders(data.providers || []);
        setActiveProvider(data.active || '');
      });
  }, []);

  const switchProvider = async (provider: string) => {
    await fetch('/api/feed/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    });
    setActiveProvider(provider);
  };

  return (
    <AppShell>
      <TopBar />
      <NavTabs tabs={TABS} active="/settings" />
      <main style={{ padding: '1.5rem', maxWidth: '800px', margin: '0 auto' }}>
        <h1 style={{ marginBottom: '1.5rem' }}>Settings</h1>

        <section style={{ marginBottom: '2rem' }}>
          <h2 style={{ marginBottom: '1rem', fontSize: '1.125rem' }}>Feed</h2>
          <div style={{
            background: '#1e293b',
            padding: '1rem',
            borderRadius: '8px',
            border: '1px solid #334155',
          }}>
            {feedStatus && (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
                  <ConnectionPill status={feedStatus.status === 'CONNECTED' ? 'connected' : 'disconnected'} />
                  <span>Active: <strong>{feedStatus.provider}</strong></span>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  {providers.map(p => (
                    <button
                      key={p}
                      onClick={() => switchProvider(p)}
                      style={{
                        padding: '0.5rem 1rem',
                        borderRadius: '4px',
                        border: 'none',
                        background: activeProvider === p ? '#38bdf8' : '#334155',
                        color: activeProvider === p ? '#0f172a' : '#cbd5e1',
                        cursor: 'pointer',
                        fontSize: '0.875rem',
                      }}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        </section>

        <section>
          <h2 style={{ marginBottom: '1rem', fontSize: '1.125rem' }}>Risk</h2>
          <div style={{
            background: '#1e293b',
            padding: '1rem',
            borderRadius: '8px',
            border: '1px solid #334155',
            color: '#94a3b8',
            fontSize: '0.875rem',
          }}>
            Risk parameters are configured via environment variables. Restart the server to apply changes.
          </div>
        </section>
      </main>
    </AppShell>
  );
}
