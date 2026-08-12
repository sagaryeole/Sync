# Deterministic Replay / Time-Travel (V1)

## Overview

Since `fills` is the append-only source of truth (H5), the portfolio state at any point in time can be rebuilt by replaying fills up to that timestamp.

## API

```
GET /api/replay?before=2026-01-01T00:00:00Z
```

If `before` is omitted, replays all fills.

**Response:**
```json
{
  "1": {"cash": 100000.0, "positions": {"BTC": 1.0}, "realized_pnl": 0.0, "fees": 0.0},
  "2": {"cash": 97000.0, "positions": {"ETH": 10.0}, "realized_pnl": 500.0, "fees": 25.0}
}
```

## Engine Method

```python
from engine.core import PaperEngine

# Rebuild as of now
result = engine.rebuild_from_fills(fills_by_strategy, marks)

# Rebuild as of a specific timestamp
result = engine.rebuild_from_fills(fills_by_strategy, marks, before_ts=datetime(2026, 1, 1, tzinfo=timezone.utc))
```

## Use Cases

- **Debugging:** "Why did it trade that?" — replay fills up to the trade timestamp
- **Audit:** Verify portfolio state at any historical point
- **Backtester seed:** Replay engine against historical fills to validate strategy changes
