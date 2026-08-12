export interface WSEnvelope {
  v: number;
  type: string;
  topic: string;
  ts: string;
  seq: number;
  data: Record<string, unknown>;
}

export type WSMessageType =
  | 'tick'
  | 'candle'
  | 'order'
  | 'fill'
  | 'position'
  | 'equity'
  | 'signal'
  | 'feed'
  | 'error'
  | 'heartbeat'
  | 'pong'
  | 'subscribed'
  | 'unsubscribed';

export interface WSClientOptions {
  url?: string;
  reconnectDelay?: number;
  maxReconnectDelay?: number;
}
