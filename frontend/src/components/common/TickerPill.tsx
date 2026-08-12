import { fmtUsd, signClass } from '../../lib/format';

interface Props {
  symbol: string;
  price: number | null | undefined;
  change?: number | null;
}

export default function TickerPill({ symbol, price, change }: Props) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900 px-3 py-1 text-sm">
      <span className={`font-semibold ${signClass(change)}`}>{symbol}</span>
      <span className="tabular-nums text-slate-400">{fmtUsd(price)}</span>
    </div>
  );
}
