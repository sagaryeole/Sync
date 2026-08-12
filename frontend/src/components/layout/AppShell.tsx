import { ReactNode, useMemo } from 'react';
import { useWebSocket } from '../../hooks/useWebSocket';

interface Props {
  children: ReactNode;
}

/**
 * App-level chrome. Also holds the baseline WebSocket subscription.
 *
 * The `feed` topic is subscribed here rather than per-page because the
 * connection indicator lives in the TopBar on every page. When only the
 * terminal subscribed, every other page showed a stale "DISCONNECTED" pill
 * while the feed was in fact healthy. wsClient is a singleton and topic
 * subscription is idempotent, so pages that need more topics (ticks,
 * candles) still add their own on top of this.
 */
export default function AppShell({ children }: Props) {
  const baseTopics = useMemo(() => ['feed'], []);
  useWebSocket(baseTopics);

  return (
    <div className="min-h-screen bg-slate-950 font-sans text-slate-100">{children}</div>
  );
}
