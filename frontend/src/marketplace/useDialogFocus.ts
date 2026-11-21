// The consent sheet's focus contract as one hook, so every marketplace
// dialog answers the same keyboard rules: focus moves in on open, Tab
// stays inside the dialog, Escape cancels, and focus returns to whatever
// opened it. Attach `sheetRef` to the role="dialog" element (which needs
// tabIndex={-1}) and `firstRef` to the control focus should land on.
import { useEffect, useRef, type RefObject } from 'react';

/**
 * Focus management for one dialog, open or closed.
 *
 * While open, focus starts on the `firstRef` element, the Tab key wraps
 * inside the `sheetRef` element, and Escape calls `onCancel`; closing
 * restores focus to the element that had it. The type parameter is the
 * element focus lands on (a button, an input), so the ref attaches
 * without a cast.
 */
export function useDialogFocus<First extends HTMLElement = HTMLElement>(
  open: boolean,
  onCancel: () => void,
): {
  sheetRef: RefObject<HTMLDivElement | null>;
  firstRef: RefObject<First | null>;
} {
  const sheetRef = useRef<HTMLDivElement>(null);
  const firstRef = useRef<First>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;

  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement;
    if (previous instanceof HTMLElement) restoreRef.current = previous;
    firstRef.current?.focus();
    /**
     * Keep the keyboard inside the open dialog: Escape cancels, and Tab wraps
     * at either end. With nothing focusable inside, focus stays on the sheet.
     */
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCancelRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const sheet = sheetRef.current;
      if (!sheet) return;
      const focusable = Array.from(sheet.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((element) => element.getAttribute('aria-hidden') !== 'true');
      if (focusable.length === 0) {
        event.preventDefault();
        sheet.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first || !sheet.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last || !sheet.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      const restore = restoreRef.current;
      restoreRef.current = null;
      if (restore && document.contains(restore)) restore.focus();
    };
  }, [open]);

  return { sheetRef, firstRef };
}
