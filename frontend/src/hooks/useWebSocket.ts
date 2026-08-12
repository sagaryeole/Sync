import { useEffect, useRef } from 'react';
import { wsClient, WSEnvelope } from '../api/ws';
import { useMarketStore } from '../store/marketSlice';

export function useWebSocket(topics: string[] = []) {
  const connectedRef = useRef(false);
  const { setLatestPrices, setFeedStatus } = useMarketStore();

  useEffect(() => {
    wsClient.connect();

    const unsub = wsClient.onMessage((envelope: WSEnvelope) => {
      if (envelope.type === 'tick' && envelope.topic === 'ticks') {
        const ticks = (envelope.data as { ticks?: Array<{ s: string; p: number }> }).ticks;
        if (Array.isArray(ticks)) {
          setLatestPrices((prev) => {
            const next = { ...prev };
            for (const t of ticks) {
              if (t && t.s && typeof t.p === 'number') {
                next[t.s] = t.p;
              }
            }
            return next;
          });
        }
      }

      // Feed status -> shared store, so every indicator agrees.
      if (envelope.type === 'feed') {
        const d = envelope.data as { status?: string; provider?: string; mode?: string };
        if (d?.status === 'CONNECTED') setFeedStatus('connected', d.provider ?? null);
        else if (d?.status === 'DEGRADED') setFeedStatus('degraded', d.provider ?? null);
        else if (d?.status === 'DISCONNECTED') setFeedStatus('disconnected', d.provider ?? null);
      }
    });

    if (topics.length > 0) {
      wsClient.subscribe(topics);
    }

    const checkInterval = setInterval(() => {
      connectedRef.current = wsClient.connected;
    }, 1000);

    return () => {
      unsub();
      clearInterval(checkInterval);
      if (topics.length > 0) {
        wsClient.unsubscribe(topics);
      }
    };
  }, [topics, setLatestPrices, setFeedStatus]);

  const connected = wsClient.connected;

  return { connected };
}
