type MessageHandler = (envelope: WSEnvelope) => void;

export interface WSEnvelope {
  v: number;
  type: string;
  topic: string;
  ts: string;
  seq: number;
  data: Record<string, unknown>;
}

type SubscriptionState = Record<string, boolean>;

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

  constructor(url = '/ws') {
    this.url = url;
  }

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;

    this.intentionalClose = false;
    this.ws = new WebSocket(this.url);

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
    for (const topic of topics) {
      this.subscriptions[topic] = true;
    }
    this.send({ op: 'subscribe', topics });
  }

  unsubscribe(topics: string[]) {
    for (const topic of topics) {
      delete this.subscriptions[topic];
    }
    this.send({ op: 'unsubscribe', topics });
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
