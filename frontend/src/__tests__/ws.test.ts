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
    vi.stubGlobal('fetch', vi.fn(async () => ({
      json: async () => ({ token: 'test-token' }),
    })));
  });

  afterEach(async () => {
    if (client) {
      client.disconnect();
    }
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('connect creates WebSocket with token', async () => {
    client = new WSClient('ws://localhost:8000/ws');
    await client.connect();
    MockWebSocket.instance!.simulateOpen();
    expect(MockWebSocket.instance).not.toBeNull();
    expect(MockWebSocket.instance!.url).toBe('ws://localhost:8000/ws?token=test-token');
  });

  it('onMessage registers handler', async () => {
    client = new WSClient('ws://localhost:8000/ws');
    await client.connect();
    MockWebSocket.instance!.simulateOpen();
    const handler = vi.fn();
    const remove = client.onMessage(handler);
    expect(typeof remove).toBe('function');
  });

  it('subscribe adds topics and sends message', async () => {
    client = new WSClient('ws://localhost:8000/ws');
    await client.connect();
    MockWebSocket.instance!.simulateOpen();
    client.subscribe(['ticks', 'orders']);
    expect(MockWebSocket.instance!.send).toHaveBeenCalledWith(JSON.stringify({ op: 'subscribe', topics: ['ticks', 'orders'] }));
  });

  it('unsubscribe removes topics and sends message', async () => {
    client = new WSClient('ws://localhost:8000/ws');
    await client.connect();
    MockWebSocket.instance!.simulateOpen();
    client.unsubscribe(['orders']);
    expect(MockWebSocket.instance!.send).toHaveBeenCalledWith(JSON.stringify({ op: 'unsubscribe', topics: ['orders'] }));
  });

  it('does not re-subscribe a topic another holder already has', async () => {
    client = new WSClient('ws://localhost:8000/ws');
    await client.connect();
    MockWebSocket.instance!.simulateOpen();

    client.subscribe(['feed']);
    MockWebSocket.instance!.send.mockClear();
    client.subscribe(['feed']); // second holder

    expect(MockWebSocket.instance!.send).not.toHaveBeenCalled();
  });

  it('keeps a shared topic alive until the last holder unsubscribes', async () => {
    // Regression: AppShell holds `feed` for the connection pill on every page
    // while the terminal also lists `feed`. With a boolean subscription map,
    // the terminal unmounting dropped the shared topic and froze the
    // indicator as DISCONNECTED everywhere else.
    client = new WSClient('ws://localhost:8000/ws');
    await client.connect();
    MockWebSocket.instance!.simulateOpen();

    client.subscribe(['feed']); // AppShell
    client.subscribe(['feed']); // TerminalPage
    MockWebSocket.instance!.send.mockClear();

    client.unsubscribe(['feed']); // TerminalPage unmounts
    expect(MockWebSocket.instance!.send).not.toHaveBeenCalled();

    client.unsubscribe(['feed']); // AppShell unmounts
    expect(MockWebSocket.instance!.send).toHaveBeenCalledWith(
      JSON.stringify({ op: 'unsubscribe', topics: ['feed'] }),
    );
  });

  it('disconnect closes socket', async () => {
    client = new WSClient('ws://localhost:8000/ws');
    await client.connect();
    MockWebSocket.instance!.simulateOpen();
    client.disconnect();
    expect(MockWebSocket.instance!.close).toHaveBeenCalled();
  });

  it('connected returns true when open', async () => {
    client = new WSClient('ws://localhost:8000/ws');
    await client.connect();
    MockWebSocket.instance!.simulateOpen();
    expect(client.connected).toBe(true);
  });

  it('onmessage parses JSON and calls handlers', async () => {
    client = new WSClient('ws://localhost:8000/ws');
    await client.connect();
    MockWebSocket.instance!.simulateOpen();
    const handler = vi.fn();
    client.onMessage(handler);

    const envelope = { v: 1, type: 'tick', topic: 'ticks', ts: '2024-01-01T00:00:00Z', seq: 1, data: {} };
    MockWebSocket.instance!.simulateMessage(JSON.stringify(envelope));

    expect(handler).toHaveBeenCalledWith(envelope);
  });

  it('onmessage ignores malformed JSON', async () => {
    client = new WSClient('ws://localhost:8000/ws');
    await client.connect();
    MockWebSocket.instance!.simulateOpen();
    const handler = vi.fn();
    client.onMessage(handler);

    MockWebSocket.instance!.simulateMessage('not json');

    expect(handler).not.toHaveBeenCalled();
  });
});
