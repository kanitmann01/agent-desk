// The 100 ms gate: nothing shows under 100 ms (a flash reads as a glitch),
// so a control starts showing busy only once the work has lasted.
import { useEffect, useState } from 'react';

/**
 * True once `active` has stayed true for `delayMs` continuously (100 ms by
 * default), and false again the moment `active` turns false. A flap shorter
 * than the delay never shows busy, and the pending timer is cleared on
 * unmount.
 */
export function useBusy(active: boolean, delayMs = 100): boolean {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (!active) {
      setShown(false);
      return;
    }
    const timer = setTimeout(() => setShown(true), delayMs);
    return () => clearTimeout(timer);
  }, [active, delayMs]);

  return active && shown;
}
