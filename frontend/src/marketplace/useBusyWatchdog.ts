// The release valve for a dialog whose request never settles: the same
// limit and sentence the server pages use, so a reader is never locked into
// a sheet until the page is reloaded.
import { useEffect, useState } from 'react';

/** The wait after which a locked dialog lets the reader leave. */
export const BUSY_WATCHDOG_MS = 180_000;

/** The sentence a dialog shows when the watchdog releases it. */
export const BUSY_WATCHDOG_TEXT =
  'This is taking too long. Check that the desk is still running, then try again.';

/**
 * True once one request has stayed pending for the whole watchdog, and false
 * again when it settles. A new request starts a fresh wait.
 */
export function useBusyWatchdog(busy: boolean, timeoutMs = BUSY_WATCHDOG_MS): boolean {
  const [released, setReleased] = useState(false);

  useEffect(() => {
    if (!busy) {
      setReleased(false);
      return undefined;
    }
    const timer = window.setTimeout(() => setReleased(true), timeoutMs);
    return () => window.clearTimeout(timer);
  }, [busy, timeoutMs]);

  return busy && released;
}
