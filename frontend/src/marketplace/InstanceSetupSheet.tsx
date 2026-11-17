// The manage view's instance-setup sheet. It is deliberately thin: it
// creates an instance and opens the workbook an instance reads, against
// the same /api/plugins endpoints the dashboard card drives, and it
// shows the server's error envelope verbatim. When the shared selection
// modal lands, the column and row steps hand over to it.
import { useEffect, useRef, useState } from 'react';
import { MarketApiError, marketErrorText, postInstance } from './client';
import type { InstanceDocument } from './types';

export type SetupTarget =
  | { mode: 'create' }
  | { mode: 'edit'; instance: InstanceDocument };

interface InstanceSetupSheetProps {
  title: string;
  pluginName: string;
  setupPluginId: string;
  target: SetupTarget;
  onCancel: () => void;
  onDone: (note: string) => void;
}

export function instanceFileName(item: InstanceDocument): string {
  const raw = item.source?.path || '';
  if (!raw) return 'Not set up';
  const base = raw.split(/[\\/]/).pop() || raw;
  return item.confirmedAt ? base : `${base} (not confirmed)`;
}

export function InstanceSetupSheet({
  title, pluginName, setupPluginId, target, onCancel, onDone,
}: InstanceSetupSheetProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;
  const [name, setName] = useState(target.mode === 'edit' ? target.instance.name : '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fileLabel, setFileLabel] = useState(
    target.mode === 'edit' ? instanceFileName(target.instance) : '');

  useEffect(() => {
    const previous = document.activeElement;
    if (previous instanceof HTMLElement) restoreRef.current = previous;
    closeRef.current?.focus();
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
  }, []);

  const create = async () => {
    setBusy(true);
    setError('');
    try {
      await postInstance<{ instance: InstanceDocument }>(setupPluginId, '', { name });
      onDone(`Created ${name || 'instance'}.`);
    } catch (err) {
      setError(marketErrorText(err));
    } finally {
      setBusy(false);
    }
  };

  const openWorkbook = async () => {
    if (target.mode !== 'edit') return;
    setBusy(true);
    setError('');
    try {
      const res = await postInstance<{ instance: InstanceDocument }>(
        setupPluginId, `/${encodeURIComponent(target.instance.instanceId)}/pick`,
        { name: target.instance.name });
      setFileLabel(instanceFileName(res.instance));
    } catch (err) {
      setError(err instanceof MarketApiError ? err.message : marketErrorText(err));
    } finally {
      setBusy(false);
    }
  };

  const isCreate = target.mode === 'create';
  const statusLabel = target.mode === 'edit'
    ? (target.instance.confirmedAt ? 'Confirmed' : 'Needs setup')
    : '';
  return (
    <div className="mkt-scrim" role="presentation">
      <div ref={sheetRef} className="mkt-sheet mkt-sheet-small" role="dialog" aria-modal="true"
           aria-labelledby="mkt-setup-title" tabIndex={-1}>
        <div className="mkt-sheet-head">
          <div>
            <span className="mkt-eyebrow">Instance setup</span>
            <h2 id="mkt-setup-title">{title}</h2>
          </div>
          <button ref={closeRef} type="button" className="mkt-icon-btn"
                  aria-label="Close instance setup" onClick={onCancel}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <div className="mkt-sheet-body">
          <p className="mkt-sheet-intro">
            {isCreate
              ? `Name the instance of ${pluginName}. Each instance keeps its own file, columns, and rows.`
              : `${target.instance.name} currently reads ${fileLabel}.`}
          </p>
          {isCreate && (
            <label className="mkt-field">
              <span>Instance name</span>
              <input value={name} onChange={(event) => setName(event.target.value)}
                     autoComplete="off" spellCheck={false} />
            </label>
          )}
          {!isCreate && (
            <p>
              <strong>{fileLabel}</strong>
              {statusLabel && <span className="mkt-sep" aria-hidden="true"> · </span>}
              {statusLabel}
            </p>
          )}
          {!isCreate && (
            <p className="w-note">
              The file dialog opens on this computer; only the file's name comes back.
            </p>
          )}
          {error && <p className="mkt-error" role="alert">{error}</p>}
        </div>
        <div className="mkt-sheet-foot">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          {isCreate ? (
            <button type="button" className="btn btn-primary" disabled={busy || !name.trim()}
                    onClick={create}>
              {busy ? 'Creating…' : 'Create instance'}
            </button>
          ) : (
            <button type="button" className="btn btn-primary" disabled={busy} onClick={openWorkbook}>
              {busy ? 'Opening…' : 'Open workbook'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
