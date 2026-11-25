// Feedback on every wait (spec 027, rules F1 to F5): the phase line a
// region shows while it is filling, the ten-second honesty line, and the
// one-page outcome channel a sheet uses when the reader closes it before
// its request answered.
import { useEffect, useState } from 'react';
import { useBusy } from './useBusy';

/** The sentence appended after ten seconds without a change (F4). */
export const SLOW_SUFFIX =
  'This is taking longer than usual. You may leave this page; the result will be here when you return.';

/** True once the work has lasted the delay; `slow` at ten seconds unchanged. */
export function usePhase(
  active: boolean,
  phaseKey = '',
  delayMs = 100,
  slowMs = 10000,
): { shown: boolean; slow: boolean } {
  const shown = useBusy(active, delayMs);
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (!active) {
      setSlow(false);
      return undefined;
    }
    setSlow(false);
    const timer = setTimeout(() => setSlow(true), slowMs);
    return () => clearTimeout(timer);
  }, [active, phaseKey, slowMs]);

  return { shown, slow };
}

/** The phase text, with the honest ten-second sentence once it is late. */
export function PhaseText({ text, slow }: { text: string; slow: boolean }) {
  return <>{slow ? `${text}. ${SLOW_SUFFIX}` : text}</>;
}

interface PhaseLineProps {
  active: boolean;
  text: string;
  /** Restarts the ten-second timer when the phase changes. */
  phaseKey?: string;
  className?: string;
  /** Mark the line itself as working, for a region that is still reading. */
  ariaBusy?: boolean;
}

/**
 * One plain line naming the phase, with a dot that pulses in colour only.
 *
 * Nothing renders under 100 ms; after ten seconds the line says the wait
 * is longer than usual and that leaving is safe.
 */
export function PhaseLine({ active, text, phaseKey = '', className = '', ariaBusy = false }: PhaseLineProps) {
  const { shown, slow } = usePhase(active, phaseKey);
  if (!shown) return null;
  return (
    <p
      className={className ? `phase-line ${className}` : 'phase-line'}
      role="status"
      aria-busy={ariaBusy ? 'true' : undefined}
    >
      <span className="btn-busy-dot" aria-hidden="true" />
      <span><PhaseText text={text} slow={slow} /></span>
    </p>
  );
}

// A tiny one-page channel: a sheet that unmounts while its request is in
// flight still reports the outcome on the page the reader returned to.
type OutcomeListener = (text: string) => void;
let outcomeListener: OutcomeListener | null = null;

/** Say an outcome on the mounted dashboard, when one is listening. */
export function announce(text: string): void {
  outcomeListener?.(text);
}

/** The latest outcome announced by a sheet that closed itself. */
export function useAnnouncement(): string {
  const [text, setText] = useState('');
  useEffect(() => {
    outcomeListener = setText;
    return () => {
      if (outcomeListener === setText) outcomeListener = null;
    };
  }, []);
  return text;
}
