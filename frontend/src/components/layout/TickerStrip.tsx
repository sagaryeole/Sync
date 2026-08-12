import { fmtUsd, fmtPct, signClass } from '../../lib/format';

interface Ticker {
  symbol: string;
  price: number | null | undefined;
  change?: number | null;
}

interface Props {
  tickers: Ticker[];
}

export default function TickerStrip({ tickers }: Props) {
  if (!tickers.length) {
    return (
      <div className="border-b border-slate-800 px-6 py-2 text-sm text-slate-500">
        Waiting for market data…
      </div>
    );
  }

  return (
    <div className="flex gap-3 overflow-x-auto border-b border-slate-800 px-6 py-2">
      {tickers.map((t) => (
        <div
          key={t.symbol}
          className="flex shrink-0 items-center gap-2 whitespace-nowrap rounded-full border border-slate-800 bg-slate-900 px-3 py-1 text-sm"
        >
          <span className="font-semibold text-slate-200">{t.symbol}</span>
          <span className="tabular-nums text-slate-400">{fmtUsd(t.price)}</span>
          {t.change !== undefined && t.change !== null && (
            <span className={`tabular-nums text-xs ${signClass(t.change)}`}>
              {fmtPct(t.change)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
