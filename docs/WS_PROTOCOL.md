# WebSocket Protocol

## Connection

```
ws://localhost:8000/ws
```

## Envelope

Every server → client message is wrapped in a versioned envelope:

```json
{
  "v": 1,
  "type": "tick",
  "topic": "ticks",
  "ts": "2026-01-01T00:00:00.000000Z",
  "seq": 42,
  "data": { ... }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `v` | int | Protocol version (currently 1) |
| `type` | string | Message type (see below) |
| `topic` | string | Topic the client subscribed to |
| `ts` | string | ISO8601 UTC timestamp |
| `seq` | int | Per-connection monotonic counter |
| `data` | object | Payload |

## Message Types

| Type | Coalesceable | Description |
|------|-------------|-------------|
| `tick` | yes | Price tick for a symbol |
| `candle` | yes | 1m candle update |
| `order` | no | Order status change |
| `fill` | no | Trade fill |
| `position` | no | Position update |
| `equity` | yes | Portfolio equity snapshot |
| `signal` | no | Strategy signal |
| `feed` | no | Feed status change |
| `error` | no | Error notification |
| `heartbeat` | no | Keep-alive ping |
| `pong` | no | Response to client ping |
| `subscribed` | no | Subscription confirmation |
| `unsubscribed` | no | Unsubscription confirmation |

## Topics

Client subscribes to topics via `{"op":"subscribe","topics":[...]}`.

| Topic | Description |
|-------|-------------|
| `ticks` | All symbol ticks |
| `candles:{SYM}:{INT}` | Candles for symbol + interval (e.g. `candles:BTC:1m`) |
| `orders` | All order updates |
| `fills` | All fills |
| `fills:{key}` | Fills for a specific strategy key |
| `positions:{key}` | Positions for a specific strategy key |
| `equity` | Equity snapshots |
| `signals` | Strategy signals |
| `feed` | Feed status changes |
| `system` | Heartbeats, errors, subscription confirmations |

Valid intervals: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`.

## Client Operations

### Subscribe

```json
{"op":"subscribe","topics":["ticks","candles:BTC:1m","equity"]}
```

Response:

```json
{"v":1,"type":"subscribed","topic":"system","ts":"...","seq":1,"data":{"topics":["ticks","candles:BTC:1m","equity"]}}
```

### Unsubscribe

```json
{"op":"unsubscribe","topics":["ticks"]}
```

### Ping

```json
{"op":"ping"}
```

Response:

```json
{"v":1,"type":"pong","topic":"system","ts":"...","seq":2,"data":{}}
```

## Errors

Invalid messages receive an error envelope:

```json
{"v":1,"type":"error","topic":"system","ts":"...","seq":3,"data":{"error":"Invalid JSON"}}
```

## Backpressure

- Each connection has a bounded queue (256 messages).
- On overflow, the server evicts the oldest **coalesceable** message (`tick`, `candle`, `equity`).
- If no coalesceable message exists, the server closes the connection with code `1013 Try Again Later`.
- `order`, `fill`, and `halt` messages are **never** dropped.

## Connection Limits (H8)

- Max **64 topics** per connection.
- Max **8 connections** per IP.
- Inbound messages are size-limited by Starlette defaults.
