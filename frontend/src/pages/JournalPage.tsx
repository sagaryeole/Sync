import { useEffect, useState } from 'react';
import AppShell from '../components/layout/AppShell';
import TopBar from '../components/layout/TopBar';
import NavTabs from '../components/layout/NavTabs';
import { Fill } from '../types/trading';
import { fmtUsd, fmtQty, fmtDateTime, signClass } from '../lib/format';

const TABS = [
  { label: 'Terminal', href: '/' },
  { label: 'Strategies', href: '/strategies' },
  { label: 'Orders', href: '/orders' },
  { label: 'Journal', href: '/journal' },
  { label: 'Settings', href: '/settings' },
];

const TH = 'px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-400';
const TD = 'px-3 py-2 text-sm';

export default function JournalPage() {
  const [fills, setFills] = useState<Fill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/fills?limit=100')
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data) => {
        if (cancelled) return;
        // Never trust the shape — an error body would crash .map() below.
        setFills(Array.isArray(data) ? data : []);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Request failed');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AppShell>
      <TopBar />
      <NavTabs tabs={TABS} active="/journal" />
      <main className="mx-auto w-full max-w-[1400px] p-6">
        <h1 className="mb-4 text-xl font-semibold text-slate-100">Trade Journal</h1>

        {error && (
          <div className="mb-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            Could not load fills: {error}
          </div>
        )}

        <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-800/50">
                <th className={TH}>Time</th>
                <th className={TH}>Symbol</th>
                <th className={TH}>Side</th>
                <th className={`${TH} text-right`}>Qty</th>
                <th className={`${TH} text-right`}>Price</th>
                <th className={`${TH} text-right`}>Fee</th>
                <th className={`${TH} text-right`}>P&amp;L</th>
                <th className={TH}>Liq</th>
              </tr>
            </thead>
            <tbody>
              {fills.map((f) => (
                <tr key={f.id} className="border-b border-slate-800/60 last:border-0 hover:bg-slate-800/30">
                  <td className={`${TD} text-slate-400`}>{fmtDateTime(f.ts)}</td>
                  <td className={`${TD} font-medium text-slate-200`}>{f.symbol}</td>
                  <td className={`${TD} ${f.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {f.side}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>{fmtQty(f.quantity, 4)}</td>
                  <td className={`${TD} text-right tabular-nums`}>{fmtUsd(f.price)}</td>
                  <td className={`${TD} text-right tabular-nums text-slate-400`}>{fmtUsd(f.fee)}</td>
                  <td className={`${TD} text-right tabular-nums ${signClass(f.realized_pnl)}`}>
                    {fmtUsd(f.realized_pnl)}
                  </td>
                  <td className={`${TD} text-slate-400`}>{f.liquidity}</td>
                </tr>
              ))}
              {loading && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-sm text-slate-500">
                    Loading…
                  </td>
                </tr>
              )}
              {!loading && fills.length === 0 && !error && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-sm text-slate-500">
                    No fills yet
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
