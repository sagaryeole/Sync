type MessageHandler = (envelope: WSEnvelope) => void;

export interface WSEnvelope {
  v: number;
  type: string;
  topic: string;
  ts: string;
  seq: number;
  data: Record<string, unknown>;
}

/**
 * Refcount per topic, not a boolean.
 *
 * Several components can want the same topic at once — AppShell holds `feed`
 * for the connection indicator on every page while the terminal also lists
 * `feed` among its own topics. With a boolean map, the terminal unmounting
 * deleted the shared topic outright and silently killed the indicator on
 * every other page. The count means a topic is only really unsubscribed once
 * the last interested component has let it go.
 */
type SubscriptionState = Record<string, number>;

export class WSClient {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: MessageHandler[] = [];
  private subscriptions: SubscriptionState = {};
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private intentionalClose = false;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private token: string | null = null;
  private connecting = false;

  constructor(url = '/ws') {
    this.url = url;
  }

  async connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    if (this.connecting) return;

    this.connecting = true;
    this.intentionalClose = false;

    try {
      if (!this.token) {
        const res = await fetch('/api/ws/token');
        const json = await res.json();
        this.token = json.token;
      }

      const url = `${this.url}?token=${this.token}`;
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        this.reconnectDelay = 1000;
        this.startHeartbeat();
        this.resubscribe();
      };

      this.ws.onmessage = (event) => {
        try {
          const envelope = JSON.parse(event.data) as WSEnvelope;
          for (const handler of this.handlers) {
            handler(envelope);
          }
        } catch {
          // ignore malformed messages
        }
      };

      this.ws.onclose = () => {
        this.stopHeartbeat();
        if (!this.intentionalClose) {
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = () => {
        this.ws?.close();
      };
    } finally {
      this.connecting = false;
    }
  }

  disconnect() {
    this.intentionalClose = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  onMessage(handler: MessageHandler) {
    this.handlers.push(handler);
    return () => {
      this.handlers = this.handlers.filter((h) => h !== handler);
    };
  }

  subscribe(topics: string[]) {
    const newTopics: string[] = [];
    for (const topic of topics) {
      const count = this.subscriptions[topic] ?? 0;
      if (count === 0) newTopics.push(topic);
      this.subscriptions[topic] = count + 1;
    }
    // Only send for topics not already held by someone else.
    if (newTopics.length > 0) {
      this.send({ op: 'subscribe', topics: newTopics });
    }
  }

  unsubscribe(topics: string[]) {
    const droppedTopics: string[] = [];
    for (const topic of topics) {
      const count = this.subscriptions[topic] ?? 0;
      if (count <= 1) {
        // Last holder (or never held) — drop it and tell the server.
        delete this.subscriptions[topic];
        droppedTopics.push(topic);
      } else {
        // Someone else still wants it; just release this holder's claim.
        this.subscriptions[topic] = count - 1;
      }
    }
    // Only tell the server once the last holder is gone.
    if (droppedTopics.length > 0) {
      this.send({ op: 'unsubscribe', topics: droppedTopics });
    }
  }

  get connected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  private send(message: Record<string, unknown>) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  private resubscribe() {
    const topics = Object.keys(this.subscriptions);
    if (topics.length > 0) {
      this.send({ op: 'subscribe', topics });
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.token = null; // force token refresh on reconnect
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
      this.connect();
    }, this.reconnectDelay);
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.send({ op: 'ping' });
    }, 15000);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }
}

export const wsClient = new WSClient();
