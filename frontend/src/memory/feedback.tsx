// Feedback primitives shared by the two memory islands. The islands are
// separate bundles with their own sheets, so they mirror the SPA Button's
// busy language here (a dot, a continuous verb, one shared label cell)
// instead of importing index.css classes.
import { useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { useBusy } from '../components/useBusy';

export { useBusy };

export type WaitPhase = 'idle' | 'working' | 'slow';

/**
 * Where a wait is on the feedback timeline.
 *
 * idle until the work starts, working after one second (the region starts
 * showing its placeholder), slow after ten seconds without a change. It
 * resets the moment active turns false.
 */
export function useWaitPhase(active: boolean): WaitPhase {
  const [phase, setPhase] = useState<WaitPhase>('idle');
  useEffect(() => {
    if (!active) {
      setPhase('idle');
      return;
    }
    const working = setTimeout(() => setPhase('working'), 1000);
    const slow = setTimeout(() => setPhase('slow'), 10000);
    return () => {
      clearTimeout(working);
      clearTimeout(slow);
    };
  }, [active]);
  return active ? phase : 'idle';
}

/** The phase line a region shows while it waits: plain, slow after 10s. */
export function WaitLine({ active, working, slow, className }: {
  active: boolean; working: string; slow: string; className?: string;
}) {
  const phase = useWaitPhase(active);
  if (phase === 'idle') return null;
  return <p className={className} role="status">{phase === 'slow' ? slow : working}</p>;
}

type WaitButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> & {
  active: boolean;
  idle: ReactNode;
  working: ReactNode;
  className?: string;
};

/**
 * A button that shows its own work from 100 ms, never changes size, and
 * cannot be pressed again while active.
 *
 * The idle and working labels share one grid cell so the hidden idle label
 * keeps the box the size it had before the work started. The dot is the only
 * addition; it pulses in place.
 */
export function WaitButton({ active, idle, working, className = '', disabled, ...rest }: WaitButtonProps) {
  const pending = useBusy(active);
  return (
    <button
      {...rest}
      type={rest.type ?? 'button'}
      className={`${className}${pending ? ' mem-pending' : ''}`}
      disabled={disabled || active}
      aria-busy={pending || undefined}
    >
      {pending && <span className="mem-busy-dot" aria-hidden="true" />}
      <span className="mem-btn-labels">
        <span className={`mem-btn-label${pending ? ' mem-btn-label-hidden' : ''}`} aria-hidden={pending || undefined}>{idle}</span>
        {pending && <span className="mem-btn-label">{working}</span>}
      </span>
    </button>
  );
}

/** A dotted wireframe line, the shape of incoming text at the same height. */
export function SkeletonLine({ className = '' }: { className?: string }) {
  return <span className={`mem-skeleton-line ${className}`.trim()} aria-hidden="true" />;
}
