// The desk's dialog shell: a scrim, the dialog role, Escape, a Tab trap
// and focus restore on close, matching the marketplace consent sheet's
// contract so every dialog on the desk behaves the same. The content is
// whatever a flow needs; busy and error ride the props as slots.
import { useEffect, useId, useRef, type ReactNode } from 'react';

export interface ModalSheetProps {
  open: boolean;
  title: string;
  onClose: () => void;
  busy?: boolean;
  error?: string;
  children: ReactNode;
}

export default function ModalSheet({ open, title, onClose, busy = false, error = '', children }: ModalSheetProps) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement;
    if (previous instanceof HTMLElement) restoreRef.current = previous;
    closeRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
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

  if (!open) return null;
  return (
    <div
      className="setup-scrim"
      data-testid="setup-scrim"
      role="presentation"
      onPointerDown={(event) => {
        // The scrim itself closes, not a release that lands on it after a
        // drag inside the sheet: pointer-down, target-checked.
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div ref={sheetRef} className="setup-sheet" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-busy={busy || undefined} tabIndex={-1}>
        <header className="setup-head">
          <h2 id={titleId}>{title}</h2>
          <button ref={closeRef} type="button" className="btn btn-secondary" onClick={onClose} aria-label="Close dialog">Close</button>
        </header>
        {children}
        {error ? <p className="alert" role="alert">{error}</p> : null}
      </div>
    </div>
  );
}
