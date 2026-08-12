import ConnectionPill from './ConnectionPill';

export default function TopBar() {
  return (
    <header className="flex items-center justify-between border-b border-slate-800 bg-slate-900 px-6 py-3">
      <div className="flex items-baseline gap-2">
        <span className="text-xl font-bold text-slate-100">CryptoTrade</span>
        <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-400">
          Paper
        </span>
      </div>
      {/* No status prop — reads the shared feed status from the store. */}
      <ConnectionPill />
    </header>
  );
}
