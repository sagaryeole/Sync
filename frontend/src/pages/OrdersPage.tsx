import { useCallback, useEffect, useState } from 'react';
import AppShell from '../components/layout/AppShell';
import TopBar from '../components/layout/TopBar';
import NavTabs from '../components/layout/NavTabs';
import { Order } from '../types/trading';
import { fmtUsd, fmtQty, fmtDateTime } from '../lib/format';

const TABS = [
  { label: 'Terminal', href: '/' },
  { label: 'Strategies', href: '/strategies' },
  { label: 'Orders', href: '/orders' },
  { label: 'Journal', href: '/journal' },
  { label: 'Settings', href: '/settings' },
];

const TH = 'px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-400';
const TD = 'px-3 py-2 text-sm';
const INPUT =
  'rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-slate-500 focus:outline-none';

/** Orders in these states are still working and can be cancelled. */
const CANCELLABLE = new Set(['PENDING', 'WORKING', 'OPEN', 'NEW', 'PARTIALLY_FILLED']);

function statusClass(status: string): string {
  if (status === 'FILLED') return 'text-emerald-400';
  if (status === 'REJECTED' || status === 'CANCELLED') return 'text-rose-400';
  return 'text-amber-400';
}

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState({ strategy: '', symbol: '', status: '' });
  const [busyId, setBusyId] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Debounce: the filter inputs fire per keystroke, and without this every
    // character issues its own request.
    const timer = setTimeout(() => {
      const params = new URLSearchParams();
      if (filter.strategy) params.set('strategy', filter.strategy);
      if (filter.symbol) params.set('symbol', filter.symbol);
      if (filter.status) params.set('status', filter.status);

      setLoading(true);
      fetch(`/api/orders?${params.toString()}`)
        .then((r) => {
          if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
          return r.json();
        })
        .then((data) => {
          if (cancelled) return;
          setOrders(Array.isArray(data) ? data : []);
          setError(null);
        })
        .catch((e) => {
          if (!cancelled) setError(e instanceof Error ? e.message : 'Request failed');
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [filter, reloadKey]);

  const cancelOrder = useCallback(async (clientOrderId: string) => {
    setBusyId(clientOrderId);
    try {
      const r = await fetch(`/api/orders/${encodeURIComponent(clientOrderId)}`, {
        method: 'DELETE',
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      setReloadKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Cancel failed');
    } finally {
      setBusyId(null);
    }
  }, []);

  return (
    <AppShell>
      <TopBar />
      <NavTabs tabs={TABS} active="/orders" />
      <main className="mx-auto w-full max-w-[1400px] p-6">
        <h1 className="mb-4 text-xl font-semibold text-slate-100">Orders</h1>

        <div className="mb-4 flex flex-wrap gap-3">
          <input
            placeholder="Strategy ID"
            value={filter.strategy}
            onChange={(e) => setFilter({ ...filter, strategy: e.target.value })}
            className={INPUT}
          />
          <input
            placeholder="Symbol"
            value={filter.symbol}
            onChange={(e) => setFilter({ ...filter, symbol: e.target.value })}
            className={INPUT}
          />
          <input
            placeholder="Status"
            value={filter.status}
            onChange={(e) => setFilter({ ...filter, status: e.target.value })}
            className={INPUT}
          />
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            {error}
          </div>
        )}

        <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-800/50">
                <th className={TH}>ID</th>
                <th className={TH}>Symbol</th>
                <th className={TH}>Side</th>
                <th className={TH}>Type</th>
                <th className={`${TH} text-right`}>Qty</th>
                <th className={`${TH} text-right`}>Filled</th>
                <th className={TH}>Status</th>
                <th className={`${TH} text-right`}>Price</th>
                <th className={TH}>Created</th>
                <th className={TH} />
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id} className="border-b border-slate-800/60 last:border-0 hover:bg-slate-800/30">
                  <td className={`${TD} text-slate-400`}>{o.id}</td>
                  <td className={`${TD} font-medium text-slate-200`}>{o.symbol}</td>
                  <td className={`${TD} ${o.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {o.side}
                  </td>
                  <td className={`${TD} text-slate-400`}>{o.order_type}</td>
                  <td className={`${TD} text-right tabular-nums`}>{fmtQty(o.quantity, 4)}</td>
                  <td className={`${TD} text-right tabular-nums`}>{fmtQty(o.filled_quantity, 4)}</td>
                  <td className={`${TD} ${statusClass(o.status)}`}>{o.status}</td>
                  <td className={`${TD} text-right tabular-nums`}>{fmtUsd(o.filled_price)}</td>
                  <td className={`${TD} text-slate-400`}>{fmtDateTime(o.created_at)}</td>
                  <td className={`${TD} text-right`}>
                    {CANCELLABLE.has(o.status) && o.client_order_id && (
                      <button
                        onClick={() => cancelOrder(o.client_order_id)}
                        disabled={busyId === o.client_order_id}
                        className="rounded border border-rose-500/40 px-2 py-1 text-xs text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
                      >
                        {busyId === o.client_order_id ? 'Cancelling…' : 'Cancel'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {loading && (
                <tr>
                  <td colSpan={10} className="px-3 py-8 text-center text-sm text-slate-500">
                    Loading…
                  </td>
                </tr>
              )}
              {!loading && orders.length === 0 && !error && (
                <tr>
                  <td colSpan={10} className="px-3 py-8 text-center text-sm text-slate-500">
                    No orders
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>
    </AppShell>
  );
}
