import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import AppShell from '../components/layout/AppShell';
import TopBar from '../components/layout/TopBar';
import NavTabs from '../components/layout/NavTabs';
import { Strategy, StrategyMetrics } from '../types/trading';
import { fmtUsd, fmtNum, fmtRatioPct, fmtDuration, signClass } from '../lib/format';

const TABS = [
  { label: 'Terminal', href: '/' },
  { label: 'Strategies', href: '/strategies' },
  { label: 'Orders', href: '/orders' },
  { label: 'Journal', href: '/journal' },
  { label: 'Settings', href: '/settings' },
];

function MetricCard({
  label,
  value,
  tone = '',
  hint,
}: {
  label: string;
  value: string;
  tone?: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`text-2xl font-bold tabular-nums ${tone}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

/** Strategy list, shown at /strategies where there is no key in the URL. */
function StrategyList() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/strategies')
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d) => {
        if (!cancelled) setStrategies(Array.isArray(d) ? d : []);
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

  if (loading) return <div className="text-sm text-slate-500">Loading…</div>;
  if (error)
    return (
      <div className="rounded-md border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
        {error}
      </div>
    );

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {strategies.map((s) => (
        <Link
          key={s.key}
          to={`/strategies/${encodeURIComponent(s.key)}`}
          className="rounded-lg border border-slate-800 bg-slate-900 p-4 transition-colors hover:border-slate-600"
        >
          <div className="flex items-center justify-between">
            <span className="font-semibold text-slate-100">{s.name}</span>
            <span
              className={`rounded-full px-2 py-0.5 text-xs ${
                s.enabled
                  ? 'bg-emerald-500/15 text-emerald-400'
                  : 'bg-slate-700/40 text-slate-400'
              }`}
            >
              {s.enabled ? 'enabled' : 'disabled'}
            </span>
          </div>
          <div className="mt-1 font-mono text-xs text-slate-500">{s.key}</div>
          <div className="mt-2 text-xs text-slate-400">{s.description}</div>
          <div className="mt-3 text-sm tabular-nums text-slate-300">
            {fmtUsd(s.starting_cash, 0)} start
          </div>
        </Link>
      ))}
      {strategies.length === 0 && (
        <div className="text-sm text-slate-500">No strategies</div>
      )}
    </div>
  );
}

export default function StrategyDetailPage() {
  const { key } = useParams<{ key: string }>();
  // Keyed together so `loading` can be derived rather than set from inside
  // the effect: a result is only current if its key matches the URL's.
  const [loaded, setLoaded] = useState<{
    key: string;
    strategy: Strategy;
    metrics: StrategyMetrics;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const current = loaded && loaded.key === key ? loaded : null;
  const strategy = current?.strategy ?? null;
  const metrics = current?.metrics ?? null;
  const loading = Boolean(key) && !metrics && !error;

  useEffect(() => {
    if (!key) return;
    let cancelled = false;

    Promise.all([
      fetch(`/api/strategies/key/${encodeURIComponent(key)}`).then((r) => {
        if (!r.ok) throw new Error('Strategy not found');
        return r.json();
      }),
      fetch(`/api/strategies/key/${encodeURIComponent(key)}/metrics`).then((r) => {
        // Previously unchecked: a 404 body was parsed as metrics, so reading
        // .win_rate off it produced undefined and crashed the render.
        if (!r.ok) throw new Error(`Metrics unavailable (${r.status})`);
        return r.json();
      }),
    ])
      .then(([strat, met]) => {
        if (cancelled) return;
        setLoaded({ key, strategy: strat, metrics: met });
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Request failed');
      });

    return () => {
      cancelled = true;
    };
  }, [key]);

  return (
    <AppShell>
      <TopBar />
      <NavTabs tabs={TABS} active="/strategies" />
      <main className="mx-auto w-full max-w-[1200px] p-6">
        <h1 className="mb-6 text-xl font-semibold text-slate-100">
          {key ? (strategy ? `${strategy.name}` : 'Strategy') : 'Strategies'}
          {key && strategy && (
            <span className="ml-2 font-mono text-sm font-normal text-slate-500">
              {strategy.key}
            </span>
          )}
        </h1>

        {!key && <StrategyList />}

        {key && error && (
          <div className="mb-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            {error}
          </div>
        )}

        {key && loading && <div className="text-sm text-slate-500">Loading…</div>}

        {key && metrics && (
          <>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-4">
              <MetricCard
                label="Total Return"
                value={fmtRatioPct(metrics.total_return_pct, 2)}
                tone={signClass(metrics.total_return_pct)}
              />
              <MetricCard label="Win Rate" value={fmtRatioPct(metrics.win_rate)} />
              <MetricCard
                label="Profit Factor"
                value={fmtNum(metrics.profit_factor)}
                hint="— when there are no losses yet"
              />
              <MetricCard
                label="Max Drawdown"
                value={fmtRatioPct(metrics.max_drawdown_pct, 2)}
              />
              <MetricCard
                label="Intraday Sharpe"
                value={fmtNum(metrics.intraday_sharpe)}
                hint="30s sampling — noisy, not a daily Sharpe"
              />
              <MetricCard label="Trades" value={fmtNum(metrics.trade_count, 0)} />
              <MetricCard
                label="Avg Win"
                value={fmtUsd(metrics.avg_win)}
                tone="text-emerald-400"
              />
              <MetricCard
                label="Avg Loss"
                value={fmtUsd(metrics.avg_loss)}
                tone="text-rose-400"
              />
              <MetricCard
                label="Avg Hold"
                value={fmtDuration(metrics.avg_hold_time_seconds)}
              />
            </div>
            <p className="mt-4 text-xs text-slate-500">
              Trend-following systems win with a low hit rate and a high win/loss size
              ratio — read win rate alongside profit factor, not on its own.
            </p>
          </>
        )}
      </main>
    </AppShell>
  );
}
