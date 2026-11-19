// One consent sheet for installs, updates and packs. It never invents a
// scope: every line comes from the server's scope list, and a widening is
// marked in text as well as colour.
import { useEffect, useRef, type ReactNode } from 'react';
import { describeScope, visibleScopes } from './permissions';

export interface ConsentSheetProps {
  open: boolean;
  title: string;
  intro: ReactNode;
  scopes: string[];
  addedScopes?: string[];
  removedScopes?: string[];
  canNever: string[];
  confirmLabel: string;
  busy?: boolean;
  error?: string;
  onCancel: () => void;
  onConfirm: () => void;
  children?: ReactNode;
}

/**
 * Render the permission review shared by installs, updates and packs.
 *
 * While open it moves focus to the close button, keeps Tab inside the dialog
 * and closes on Escape; closing returns focus to whatever had it before. Only
 * positive scopes are listed, and a scope in `addedScopes` is marked as new in
 * text as well as colour.
 */
export function ConsentSheet({
  open, title, intro, scopes, addedScopes = [], removedScopes = [],
  canNever, confirmLabel, busy = false, error = '', onCancel, onConfirm, children,
}: ConsentSheetProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;
  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement;
    if (previous instanceof HTMLElement) restoreRef.current = previous;
    closeRef.current?.focus();
    /**
     * Keep the keyboard inside the open sheet: Escape cancels, and Tab wraps at
     * either end. With nothing focusable inside, focus stays on the sheet.
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

  if (!open) return null;
  const added = new Set(addedScopes);
  const shown = visibleScopes(scopes);
  return (
    <div className="mkt-scrim" role="presentation">
      <div ref={sheetRef} className="mkt-sheet" role="dialog" aria-modal="true" aria-labelledby="mkt-consent-title" tabIndex={-1}>
        <div className="mkt-sheet-head">
          <div>
            <span className="mkt-eyebrow">Permission review</span>
            <h2 id="mkt-consent-title">{title}</h2>
          </div>
          <button ref={closeRef} type="button" className="mkt-icon-btn"
                  aria-label="Close permission review" onClick={onCancel}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <div className="mkt-sheet-body">
          <p className="mkt-sheet-intro">{intro}</p>
          <section aria-labelledby="mkt-consent-scopes">
            <h3 id="mkt-consent-scopes">What it can use</h3>
            {shown.length === 0 ? (
              <p className="mkt-empty-inline">It asks for no data access.</p>
            ) : (
              <ul className="mkt-scope-list">
                {shown.map((scope) => {
                  const meaning = describeScope(scope);
                  return (
                    <li key={scope} className={added.has(scope) ? 'is-added' : ''}>
                      <span className="mkt-scope-sentence">{meaning.sentence}</span>
                      <span className="w-note">You control this under {meaning.setting}.</span>
                      <span className="mkt-mono mkt-scope-raw">{scope}</span>
                      {added.has(scope) && <span className="mkt-chip mkt-chip-warn">New in this version</span>}
                    </li>
                  );
                })}
              </ul>
            )}
            {addedScopes.length > 0 && (
              <p className="mkt-sheet-callout">
                This update widens access: {addedScopes.length} new scope
                {addedScopes.length === 1 ? '' : 's'} marked above.
              </p>
            )}
            {removedScopes.length > 0 && (
              <p className="mkt-sheet-note">
                The new version drops {removedScopes.length} scope{removedScopes.length === 1 ? '' : 's'}.
              </p>
            )}
          </section>
          <section aria-labelledby="mkt-consent-never">
            <h3 id="mkt-consent-never">What it can never do</h3>
            <ul className="mkt-never-list">
              {canNever.map((line) => <li key={line}>{line}</li>)}
            </ul>
          </section>
          {children}
          {error && <p className="mkt-error mkt-error-inline" role="alert">{error}</p>}
        </div>
        <div className="mkt-sheet-foot">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button ref={confirmRef} type="button" className="btn btn-primary"
                  disabled={busy} onClick={onConfirm}>
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
