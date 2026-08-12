import { ReactNode } from 'react';
import { ErrorBoundary } from './ErrorBoundary';

interface Props {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Removes the default body padding, for panels that hold a flush table. */
  flush?: boolean;
}

/**
 * A dashboard panel that contains its own failures.
 *
 * Each panel wraps its children in an ErrorBoundary so a render throw inside
 * one panel degrades to an inline "Panel error" message instead of unmounting
 * the whole terminal. Without this, a single bad field anywhere on the page
 * blanks every other panel too — including the ones showing live positions.
 */
export default function Panel({ title, actions, children, className = '', flush }: Props) {
  return (
    <section
      className={`flex min-w-0 flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-900 ${className}`}
    >
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-slate-800 px-4 py-2.5">
          {typeof title === 'string' ? (
            <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
          ) : (
            title
          )}
          {actions}
        </header>
      )}
      <div className={flush ? 'min-h-0 flex-1 overflow-auto' : 'min-h-0 flex-1 overflow-auto p-4'}>
        <ErrorBoundary
          fallback={
            <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-300">
              Panel error — this section failed to render. The rest of the terminal is
              unaffected.
            </div>
          }
        >
          {children}
        </ErrorBoundary>
      </div>
    </section>
  );
}
