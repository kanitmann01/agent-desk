// Installed plugins: what is running, what is pinned, what needs a
// decision. Every control posts once and then re-reads the installed list;
// no row changes state before the server answers.
import { useCallback, useEffect, useState } from 'react';
import Button from '../components/Button';
import EmptyState, { ICON_SHEET } from '../components/EmptyState';
import { getMarket, marketErrorText, postMarket } from './client';
import { ConsentSheet } from './ConsentSheet';
import { MarketLink } from './context';
import { canNeverFromScopes, formatBytes, formatDate, pilotBudget, shortDigest, visibleScopes } from './permissions';
import { StatusChip } from './StatusChip';
import { useDialogFocus } from './useDialogFocus';
import type { InstalledResponse, InstalledSummary } from './types';

type Load =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: InstalledResponse };

type Confirm =
  | { kind: 'rollback'; record: InstalledSummary }
  | { kind: 'uninstall'; record: InstalledSummary }
  | null;

/**
 * Render the typed confirmation that deletes a plugin's data and install
 * record.
 *
 * The confirm button stays disabled until the input matches
 * `delete-data:<id>` exactly, because there is no undo.
 */
function PurgeDialog({ record, busy, error, onCancel, onConfirm }: {
  record: InstalledSummary;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const [typed, setTyped] = useState('');
  const expected = `delete-data:${record.id}`;
  const { sheetRef, firstRef } = useDialogFocus<HTMLInputElement>(true, onCancel);
  return (
    <div className="mkt-scrim" role="presentation">
      <div ref={sheetRef} className="mkt-sheet mkt-sheet-small" role="dialog" aria-modal="true" aria-labelledby="mkt-purge-title" tabIndex={-1}>
        <div className="mkt-sheet-head">
          <div>
            <span className="mkt-eyebrow">Destructive action</span>
            <h2 id="mkt-purge-title">Purge data for {record.name}</h2>
          </div>
        </div>
        <div className="mkt-sheet-body">
          <p>This deletes {formatBytes(record.dataDirSize)} of plugin data and its install record. There is no undo.</p>
          <label className="mkt-field">
            <span>Type <code>{expected}</code> to confirm</span>
            <input ref={firstRef} value={typed} onChange={(event) => setTyped(event.target.value)}
                   autoComplete="off" spellCheck={false} />
          </label>
          {error && <p className="mkt-error" role="alert">{error}</p>}
        </div>
        <div className="mkt-sheet-foot">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={typed !== expected || busy}
                  onClick={onConfirm}>
            {busy ? 'Purging…' : 'Purge data'}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Render the installed list with each plugin's update, sharing and lifecycle
 * controls.
 *
 * Every control posts once and then re-reads the list, so a row never changes
 * before the server answers. An update that leaves a permission change
 * pending opens the review on the refreshed record, which is what makes the
 * sheet show the staged scopes rather than a guess.
 */
export function InstalledPage() {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [busyId, setBusyId] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [consentRecord, setConsentRecord] = useState<InstalledSummary | null>(null);
  const [sheetError, setSheetError] = useState('');
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [purgeRecord, setPurgeRecord] = useState<InstalledSummary | null>(null);
  const [purgeError, setPurgeError] = useState('');
  const confirmFocus = useDialogFocus<HTMLButtonElement>(confirm !== null, () => setConfirm(null));

  const loadList = useCallback(async () => {
    try {
      const data = await getMarket<InstalledResponse>('/api/marketplace/installed');
      setLoad({ kind: 'ready', data });
      return data;
    } catch (err) {
      setLoad({ kind: 'error', message: marketErrorText(err) });
      return null;
    }
  }, []);

  useEffect(() => { void loadList(); }, [loadList, attempt]);

  /**
   * Run one mutation for a record, show the note it returns, then re-read the
   * list.
   *
   * The record's id stays busy for the duration, and a failure replaces the
   * note with the server's message; nothing is re-read in that case.
   */
  const run = async (record: InstalledSummary, fn: () => Promise<string>) => {
    setBusyId(record.id);
    setError('');
    setMessage('');
    try {
      const note = await fn();
      setMessage(note);
      await loadList();
    } catch (err) {
      setError(marketErrorText(err));
    } finally {
      setBusyId('');
    }
  };

  /** Enable or disable one plugin, reporting the state the server settled on. */
  const toggle = (record: InstalledSummary) => run(record, async () => {
    const action = record.enabled ? 'disable' : 'enable';
    const res = await postMarket<{ state?: string }>(`/api/marketplace/${action}`, { id: record.id });
    return `${record.name} is now ${res.state ?? (record.enabled ? 'disabled' : 'enabled')}.`;
  });

  /**
   * Share one plugin with paired desks, or stop sharing it.
   *
   * Sharing with no desk paired still succeeds and says so: the plugin is
   * shared before any peer exists, and the note points at where pairing
   * happens.
   */
  const toggleShare = (record: InstalledSummary) => run(record, async () => {
    const sharing = !record.shared;
    const res = await postMarket<{ paired?: number }>(
      `/api/marketplace/${sharing ? 'share' : 'unshare'}`, { id: record.id });
    if (!sharing) return `${record.name} is no longer shared.`;
    return res.paired
      ? `${record.name} is now shared with paired desks.`
      : `${record.name} is shared, but no desks are paired yet. Pair a desk under Peers.`;
  });

  /**
   * Apply the staged update, then open the permission review when the new
   * version left one pending.
   *
   * The refreshed list is what decides that, so the sheet describes the
   * scopes the server staged.
   */
  const reviewUpdate = async (record: InstalledSummary) => {
    setBusyId(record.id);
    setError('');
    setMessage('');
    try {
      const res = await postMarket<{ from: string; to: string; pendingConsent: boolean }>(
        '/api/marketplace/update', { id: record.id });
      setMessage(res.pendingConsent
        ? `Updated to ${res.to}; consent for the new scopes is still pending.`
        : `Updated ${record.name} to ${res.to}.`);
      const refreshed = await loadList();
      const updated = refreshed?.plugins.find((item) => item.id === record.id);
      if (updated?.pendingConsent) {
        setSheetError('');
        setConsentRecord(updated);
      }
    } catch (err) {
      setError(marketErrorText(err));
    } finally {
      setBusyId('');
    }
  };

  /**
   * Accept the staged update's new scopes, name the version now running and
   * close the sheet.
   *
   * A failure keeps the sheet open with the server's message.
   */
  const acceptConsent = async () => {
    if (!consentRecord) return;
    setBusyId(consentRecord.id);
    setSheetError('');
    try {
      const res = await postMarket<{ version: string }>('/api/marketplace/consent',
        { id: consentRecord.id, decision: 'accept' });
      setMessage(`${consentRecord.name} updated to ${res.version}.`);
      setConsentRecord(null);
      await loadList();
    } catch (err) {
      setSheetError(marketErrorText(err));
    } finally {
      setBusyId('');
    }
  };

  /**
   * Refuse the staged update's new scopes, leaving the installed version in
   * place.
   *
   * The note names the version the plugin stays on.
   */
  const declineConsent = async (record: InstalledSummary) => {
    setBusyId(record.id);
    setSheetError('');
    try {
      const res = await postMarket<{ version: string }>('/api/marketplace/consent',
        { id: record.id, decision: 'reject' });
      setMessage(`Update declined. ${record.name} stays on ${res.version}.`);
      setConsentRecord(null);
      await loadList();
    } catch (err) {
      setSheetError(marketErrorText(err));
    } finally {
      setBusyId('');
    }
  };

  /**
   * Close the pending confirmation and run the action it named.
   *
   * Uninstall keeps the plugin's data folder; only a purge deletes it.
   */
  const doConfirm = () => {
    if (!confirm) return;
    const { kind, record } = confirm;
    setConfirm(null);
    if (kind === 'rollback') {
      void run(record, async () => {
        const res = await postMarket<{ from: string; to: string }>('/api/marketplace/rollback', { id: record.id });
        return `Rolled back ${record.name} from ${res.from} to ${res.to}.`;
      });
    } else {
      void run(record, async () => {
        await postMarket('/api/marketplace/uninstall', { id: record.id });
        return `${record.name} uninstalled. Its data folder was kept.`;
      });
    }
  };

  /**
   * Delete the plugin's data and install record, then close the dialog.
   *
   * The literal `delete-data:<id>` is sent as the confirmation token; a
   * refusal keeps the dialog open with the server's message.
   */
  const doPurge = async () => {
    if (!purgeRecord) return;
    setBusyId(purgeRecord.id);
    setPurgeError('');
    try {
      await postMarket('/api/marketplace/purge-data',
        { id: purgeRecord.id, confirm: `delete-data:${purgeRecord.id}` });
      setMessage(`${purgeRecord.name} data purged.`);
      setPurgeRecord(null);
      await loadList();
    } catch (err) {
      setPurgeError(marketErrorText(err));
    } finally {
      setBusyId('');
    }
  };

  return (
    <div className="mkt-page">
      <header className="mkt-page-head">
        <span className="mkt-eyebrow">Plugins</span>
        <h1>Installed plugins</h1>
        <p className="mkt-lede">
          Each plugin runs with only the scopes you approved. Pinned versions and digests are shown before an update.
        </p>
      </header>

      {error && <p className="mkt-error" role="alert">{error}</p>}
      {message && <p className="mkt-success" role="status">{message}</p>}

      {load.kind === 'loading' && <p className="mkt-result-count" aria-busy="true">Loading installed plugins…</p>}
      {load.kind === 'error' && (
        <div className="mkt-error-panel" role="alert">
          <h2>The installed list did not load</h2>
          <p>{load.message}</p>
          <Button tone="secondary" onClick={() => setAttempt((n) => n + 1)}>Try again</Button>
        </div>
      )}
      {load.kind === 'ready' && load.data.plugins.length === 0 && (
        <EmptyState
          icon={ICON_SHEET}
          action={<MarketLink className="btn btn-secondary" to="/marketplace">Browse the marketplace</MarketLink>}
        >
          <span>Nothing is installed yet.</span>
          <span className="w-note mkt-empty-line">Plugins install from the marketplace, one at a time.</span>
        </EmptyState>
      )}
      {load.kind === 'ready' && load.data.plugins.length > 0 && (
        <ul className="mkt-installed" role="list">
          {load.data.plugins.map((record) => (
            <li key={record.id}>
              <article className="mkt-installed-card" aria-labelledby={`inst-${record.id}`}>
                <div className="mkt-installed-head">
                  <div>
                    <h2 id={`inst-${record.id}`}>
                      <MarketLink to={`/marketplace/plugin/${encodeURIComponent(record.id)}`}>{record.name}</MarketLink>
                    </h2>
                    <p className="mkt-installed-meta">
                      <span className="mkt-mono">v{record.pinned.version}</span>
                      <span className="mkt-sep" aria-hidden="true">·</span>
                      <span className="mkt-mono" title={record.pinned.sha256}>sha256:{shortDigest(record.pinned.sha256)}</span>
                      <span className="mkt-sep" aria-hidden="true">·</span>
                      <StatusChip status={record.status.status} />
                      {record.shared && <><span className="mkt-sep" aria-hidden="true">·</span><span className="mkt-chip">Shared</span></>}
                    </p>
                  </div>
                  <div className="mkt-installed-flags">
                    <span className="mkt-chip">Pilot: {pilotBudget(record.pilot)}</span>
                    <span className="w-note">Data {formatBytes(record.dataDirSize)}</span>
                    <span className="w-note">Validated {formatDate(record.status.checked_at)}</span>
                  </div>
                </div>

                {record.status.cause && <p className="mkt-attention">{record.status.cause}</p>}

                {record.pendingConsent ? (
                  <div className="mkt-update-row">
                    <p>
                      <strong>Permission change needs review.</strong>{' '}
                      {record.update
                        ? `The staged version adds ${record.update.widening.length} scope${record.update.widening.length === 1 ? '' : 's'}.`
                        : 'Open the review to see the staged scopes.'}
                    </p>
                    <div className="mkt-actions">
                      <Button tone="primary" disabled={busyId === record.id}
                              onClick={() => { setSheetError(''); setConsentRecord(record); }}>
                        Review update
                      </Button>
                      <Button tone="secondary" disabled={busyId === record.id}
                              onClick={() => void declineConsent(record)}>
                        Decline
                      </Button>
                    </div>
                  </div>
                ) : record.update ? (
                  <div className="mkt-update-row">
                    <p>
                      <strong>Update available: v{record.update.version}.</strong>{' '}
                      {record.update.widening.length > 0
                        ? `It adds ${record.update.widening.length} permission scope${record.update.widening.length === 1 ? '' : 's'}.`
                        : 'It asks for no new permissions.'}
                    </p>
                    <Button tone="primary" disabled={busyId === record.id}
                            onClick={() => void reviewUpdate(record)}>
                      Review and update
                    </Button>
                  </div>
                ) : (
                  <p className="w-note">Up to date. No update is waiting.</p>
                )}

                <div className="mkt-actions mkt-installed-actions">
                  <Button tone="secondary" disabled={busyId === record.id} onClick={() => void toggle(record)}>
                    {record.enabled ? 'Disable' : 'Enable'}
                  </Button>
                  <Button tone="secondary" disabled={busyId === record.id}
                          onClick={() => void toggleShare(record)}>
                    {record.shared ? 'Stop sharing' : 'Share with peers'}
                  </Button>
                  <Button tone="secondary" disabled={busyId === record.id}
                          onClick={() => setConfirm({ kind: 'rollback', record })}>
                    Roll back
                  </Button>
                  <Button tone="secondary" disabled={busyId === record.id}
                          onClick={() => { setPurgeError(''); setPurgeRecord(record); }}>
                    Purge data
                  </Button>
                  <Button tone="secondary" disabled={busyId === record.id}
                          onClick={() => setConfirm({ kind: 'uninstall', record })}>
                    Uninstall
                  </Button>
                </div>
              </article>
            </li>
          ))}
        </ul>
      )}

      <ConsentSheet
        open={consentRecord !== null}
        title={consentRecord ? `Review update for ${consentRecord.name}` : 'Review update'}
        intro="The staged version asks for the scopes below. Nothing runs with them until you accept."
        scopes={consentRecord?.update?.scopes ?? []}
        addedScopes={consentRecord?.update?.widening ?? []}
        canNever={canNeverFromScopes(consentRecord?.update?.scopes ?? [])}
        confirmLabel="Accept update"
        busy={busyId === consentRecord?.id}
        error={sheetError}
        onCancel={() => { if (!busyId) setConsentRecord(null); }}
        onConfirm={() => void acceptConsent()}
      >
        {consentRecord && visibleScopes(consentRecord.update?.scopes ?? []).length === 0 && (
          <p className="mkt-empty-inline">The staged version declares no new data access.</p>
        )}
      </ConsentSheet>

      {purgeRecord && (
        <PurgeDialog record={purgeRecord} busy={busyId === purgeRecord.id} error={purgeError}
                     onCancel={() => setPurgeRecord(null)} onConfirm={() => void doPurge()} />
      )}

      {confirm && (
        <div className="mkt-scrim" role="presentation">
          <div ref={confirmFocus.sheetRef} className="mkt-sheet mkt-sheet-small" role="dialog" aria-modal="true" aria-labelledby="mkt-confirm-title" tabIndex={-1}>
            <div className="mkt-sheet-head">
              <h2 id="mkt-confirm-title">
                {confirm.kind === 'rollback' ? `Roll back ${confirm.record.name}` : `Uninstall ${confirm.record.name}`}
              </h2>
            </div>
            <div className="mkt-sheet-body">
              <p>{confirm.kind === 'rollback'
                ? 'The previous installed version becomes active. The current version stays in history.'
                : 'The plugin stops running. Its data folder is kept until you purge it.'}</p>
            </div>
            <div className="mkt-sheet-foot">
              <button ref={confirmFocus.firstRef} type="button" className="btn btn-secondary" onClick={() => setConfirm(null)}>Cancel</button>
              <button type="button" className="btn btn-primary" onClick={doConfirm}>
                {confirm.kind === 'rollback' ? 'Roll back' : 'Uninstall'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
