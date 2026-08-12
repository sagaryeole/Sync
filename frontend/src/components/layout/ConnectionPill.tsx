import { useMarketStore, FeedStatus } from '../../store/marketSlice';

interface Props {
  /** Omit to read the shared feed status from the store (the usual case). */
  status?: FeedStatus;
  label?: string;
}

const DOT: Record<FeedStatus, string> = {
  connected: 'bg-emerald-400',
  disconnected: 'bg-rose-400',
  degraded: 'bg-amber-400',
};

const TEXT: Record<FeedStatus, string> = {
  connected: 'text-emerald-400',
  disconnected: 'text-rose-400',
  degraded: 'text-amber-400',
};

export default function ConnectionPill({ status, label }: Props) {
  const storeStatus = useMarketStore((s) => s.feedStatus);
  const provider = useMarketStore((s) => s.feedProvider);
  // Defaulting the prop to 'disconnected' is what made TopBar permanently red
  // regardless of the real feed state — fall back to the store instead.
  const effective = status ?? storeStatus;

  return (
    <div
      className="inline-flex items-center gap-2 rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-xs font-medium uppercase tracking-wider"
      title={provider ? `Provider: ${provider}` : undefined}
    >
      <span className={`h-2 w-2 rounded-full ${DOT[effective]}`} />
      <span className={TEXT[effective]}>{label || effective}</span>
      {provider && <span className="text-slate-500 normal-case">· {provider}</span>}
    </div>
  );
}
