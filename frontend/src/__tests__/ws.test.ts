import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { WSClient } from '../api/ws';

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  send = vi.fn();
  close = vi.fn();
  addEventListener = vi.fn();
  removeEventListener = vi.fn();
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  static instance: MockWebSocket | null = null;

  constructor(public url: string) {
    MockWebSocket.instance = this;
  }

  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    if (this.onopen) this.onopen();
  }

  simulateMessage(data: string) {
    if (this.onmessage) this.onmessage({ data });
  }

  simulateClose() {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose();
  }
}

describe('WSClient', () => {
  let client: WSClient;

  beforeEach(() => {
    MockWebSocket.instance = null;
    (globalThis as unknown as { WebSocket: typeof MockWebSocket }).WebSocket = MockWebSocket;
    client = new WSClient('ws://localhost:8000/ws');
    client.connect();
    MockWebSocket.instance!.simulateOpen();
    vi.useFakeTimers();
  });

  afterEach(() => {
    client.disconnect();
    vi.useRealTimers();
  });

  it('connect creates WebSocket', () => {
    expect(MockWebSocket.instance).not.toBeNull();
    expect(MockWebSocket.instance!.url).toBe('ws://localhost:8000/ws');
  });

  it('onMessage registers handler', () => {
    const handler = vi.fn();
    const remove = client.onMessage(handler);
    expect(typeof remove).toBe('function');
  });

  it('subscribe adds topics and sends message', () => {
    client.subscribe(['ticks', 'orders']);
    expect(MockWebSocket.instance!.send).toHaveBeenCalledWith(JSON.stringify({ op: 'subscribe', topics: ['ticks', 'orders'] }));
  });

  it('unsubscribe removes topics and sends message', () => {
    client.unsubscribe(['orders']);
    expect(MockWebSocket.instance!.send).toHaveBeenCalledWith(JSON.stringify({ op: 'unsubscribe', topics: ['orders'] }));
  });

  it('disconnect closes socket', () => {
    client.disconnect();
    expect(MockWebSocket.instance!.close).toHaveBeenCalled();
  });

  it('connected returns true when open', () => {
    expect(client.connected).toBe(true);
  });

  it('onmessage parses JSON and calls handlers', () => {
    const handler = vi.fn();
    client.onMessage(handler);

    const envelope = { v: 1, type: 'tick', topic: 'ticks', ts: '2024-01-01T00:00:00Z', seq: 1, data: {} };
    MockWebSocket.instance!.simulateMessage(JSON.stringify(envelope));

    expect(handler).toHaveBeenCalledWith(envelope);
  });

  it('onmessage ignores malformed JSON', () => {
    const handler = vi.fn();
    client.onMessage(handler);

    MockWebSocket.instance!.simulateMessage('not json');

    expect(handler).not.toHaveBeenCalled();
  });
});
