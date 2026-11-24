// Installed plugins: what is running, what is pinned, what needs a
// decision. Every control posts once and then re-reads the installed list;
// no row changes state before the server answers.
import { useCallback, useEffect, useState } from 'react';
import Button from '../components/Button';
import { useBusy } from '../components/useBusy';
import EmptyState, { ICON_SHEET } from '../components/EmptyState';
import { getMarket, marketErrorText, postMarket } from './client';
import { ConsentSheet } from './ConsentSheet';
import { MarketLink } from './context';
import { asksForWeb, canNeverFromScopes, formatBytes, formatDate, pilotBudget, shortDigest, visibleScopes } from './permissions';
import { StatusChip } from './StatusChip';
import { useDialogFocus } from './useDialogFocus';
import type { DetailResponse, InstalledResponse, InstalledSummary } from './types';

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
            <span>Type <code tabIndex={0} title={expected}>{expected}</code> to confirm</span>
            <input ref={firstRef} value={typed} onChange={(event) => setTyped(event.target.value)}
                   autoComplete="off" spellCheck={false} />
          </label>
          {error && <p className="mkt-error" role="alert">{error}</p>}
        </div>
        <div className="mkt-sheet-foot">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={typed !== expected || busy}
                  aria-busy={busy ? 'true' : undefined}
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
  // The record and action in flight, so the pressed control names the work
  // and its own row carries aria-busy.
  const [busy, setBusy] = useState<{ id: string; action: string } | null>(null);
  const busyShown = useBusy(busy !== null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [consentRecord, setConsentRecord] = useState<InstalledSummary | null>(null);
  const [sheetError, setSheetError] = useState('');
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [purgeRecord, setPurgeRecord] = useState<InstalledSummary | null>(null);
  const [purgeError, setPurgeError] = useState('');
  const [cannotRunIds, setCannotRunIds] = useState<Set<string>>(() => new Set());
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

  // The list DTO carries no capability block, so when the desk has no HTTP
  // transport each installed plugin's detail DTO is read once to learn
  // whether it asks for the web. A failed read claims nothing.
  useEffect(() => {
    if (load.kind !== 'ready' || load.data.deskNetwork !== false) {
      setCannotRunIds((current) => (current.size === 0 ? current : new Set()));
      return undefined;
    }
    let cancelled = false;
    void Promise.all(load.data.plugins.map(async (record) => {
      try {
        const data = await getMarket<DetailResponse>(
          `/api/marketplace/plugin/${encodeURIComponent(record.id)}`);
        return asksForWeb(data.plugin.capabilities) ? record.id : '';
      } catch {
        return '';
      }
    })).then((ids) => {
      if (!cancelled) setCannotRunIds(new Set(ids.filter(Boolean)));
    });
    return () => { cancelled = true; };
  }, [load]);

  /**
   * Run one mutation for a record, show the note it returns, then re-read the
   * list.
   *
   * The record and action stay busy for the duration, so the pressed control
   * can carry the continuous verb, and a failure replaces the note with the
   * server's message; nothing is re-read in that case.
   */
  const run = async (record: InstalledSummary, action: string, fn: () => Promise<string>) => {
    setBusy({ id: record.id, action });
    setError('');
    setMessage('');
    try {
      const note = await fn();
      setMessage(note);
      await loadList();
    } catch (err) {
      setError(marketErrorText(err));
    } finally {
      setBusy(null);
    }
  };

  /** Enable or disable one plugin, reporting the state the server settled on. */
  const toggle = (record: InstalledSummary) => {
    const action = record.enabled ? 'disable' : 'enable';
    return run(record, action, async () => {
      const res = await postMarket<{ state?: string }>(`/api/marketplace/${action}`, { id: record.id });
      return `${record.name} is now ${res.state ?? (record.enabled ? 'disabled' : 'enabled')}.`;
    });
  };

  /**
   * Share one plugin with paired desks, or stop sharing it.
   *
   * Sharing with no desk paired still succeeds and says so: the plugin is
   * shared before any peer exists, and the note points at where pairing
   * happens.
   */
  const toggleShare = (record: InstalledSummary) => {
    const sharing = !record.shared;
    return run(record, sharing ? 'share' : 'unshare', async () => {
      const res = await postMarket<{ paired?: number }>(
        `/api/marketplace/${sharing ? 'share' : 'unshare'}`, { id: record.id });
      if (!sharing) return `${record.name} is no longer shared.`;
      return res.paired
        ? `${record.name} is now shared with paired desks.`
        : `${record.name} is shared, but no desks are paired yet. Pair a desk under Peers.`;
    });
  };

  /**
   * Apply the staged update, then open the permission review when the new
   * version left one pending.
   *
   * The refreshed list is what decides that, so the sheet describes the
   * scopes the server staged.
   */
  const reviewUpdate = async (record: InstalledSummary) => {
    setBusy({ id: record.id, action: 'update' });
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
      setBusy(null);
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
    setBusy({ id: consentRecord.id, action: 'consent' });
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
      setBusy(null);
    }
  };

  /**
   * Refuse the staged update's new scopes, leaving the installed version in
   * place.
   *
   * The note names the version the plugin stays on.
   */
  const declineConsent = async (record: InstalledSummary) => {
    setBusy({ id: record.id, action: 'decline' });
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
      setBusy(null);
    }
  };

  /**
   * Run the action the open confirmation named, keeping the dialog up with
   * its button working until the server answers, then close it.
   *
   * Uninstall keeps the plugin's data folder; only a purge deletes it.
   */
  const doConfirm = async () => {
    if (!confirm) return;
    const { kind, record } = confirm;
    if (kind === 'rollback') {
      await run(record, 'rollback', async () => {
        const res = await postMarket<{ from: string; to: string }>('/api/marketplace/rollback', { id: record.id });
        return `Rolled back ${record.name} from ${res.from} to ${res.to}.`;
      });
    } else {
      await run(record, 'uninstall', async () => {
        await postMarket('/api/marketplace/uninstall', { id: record.id });
        return `${record.name} uninstalled. Its data folder was kept.`;
      });
    }
    setConfirm(null);
  };

  /**
   * Delete the plugin's data and install record, then close the dialog.
   *
   * The literal `delete-data:<id>` is sent as the confirmation token; a
   * refusal keeps the dialog open with the server's message.
   */
  const doPurge = async () => {
    if (!purgeRecord) return;
    setBusy({ id: purgeRecord.id, action: 'purge' });
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
      setBusy(null);
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

      {load.kind === 'loading' && (
        <div className="mkt-installed-skeleton" aria-busy="true">
          <p className="mkt-result-count" role="status">Reading installed plugins…</p>
          <ul className="mkt-installed" role="list" aria-hidden="true">
            {[0, 1].map((n) => (
              <li key={n}>
                <div className="mkt-installed-card mkt-installed-skel">
                  <span className="mkt-skel mkt-skel-title" />
                  <span className="mkt-skel" />
                  <span className="mkt-skel mkt-skel-short" />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
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
          {load.data.plugins.map((record) => {
            const cannotRun = cannotRunIds.has(record.id);
            const rowBusy = busy?.id === record.id;
            /** True while this record's exact action is past the 100 ms gate. */
            const pendingFor = (action: string) => (
              busyShown && busy !== null && busy.id === record.id && busy.action === action
            );
            return (
            <li key={record.id}>
              <article className="mkt-installed-card" aria-labelledby={`inst-${record.id}`}
                       aria-busy={rowBusy ? 'true' : undefined}>
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
                    {cannotRun && <span className="mkt-chip" title="Cannot run on this desk">Cannot run on this desk</span>}
                    <span className="mkt-chip" title={`Pilot: ${pilotBudget(record.pilot)}`}>Pilot: {pilotBudget(record.pilot)}</span>
                    <span className="w-note">Data {formatBytes(record.dataDirSize)}</span>
                    <span className="w-note">Validated {formatDate(record.status.checked_at)}</span>
                  </div>
                </div>

                {record.status.cause && !cannotRun && <p className="mkt-attention">{record.status.cause}</p>}

                {cannotRun && (
                  <>
                    <div className="mkt-attention">
                      <strong>Cannot run on this desk.</strong>{' '}
                      <span>This desk cannot read web pages yet, so this plugin cannot run here.</span>
                    </div>
                    <div className="mkt-actions">
                      <Button tone="primary" disabled={rowBusy}
                              onClick={() => setConfirm({ kind: 'uninstall', record })}>
                        Remove
                      </Button>
                    </div>
                  </>
                )}

                {!cannotRun && (record.pendingConsent ? (
                  <div className="mkt-update-row">
                    <p>
                      <strong>Permission change needs review.</strong>{' '}
                      {record.update
                        ? `The staged version adds ${record.update.widening.length} scope${record.update.widening.length === 1 ? '' : 's'}.`
                        : 'Open the review to see the staged scopes.'}
                    </p>
                    <div className="mkt-actions">
                      <Button tone="primary" disabled={rowBusy}
                              onClick={() => { setSheetError(''); setConsentRecord(record); }}>
                        Review update
                      </Button>
                      <Button tone="secondary" disabled={rowBusy}
                              pending={pendingFor('decline')} pendingLabel="Declining…"
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
                    <Button tone="primary" disabled={rowBusy}
                            pending={pendingFor('update')} pendingLabel="Reviewing the update…"
                            onClick={() => void reviewUpdate(record)}>
                      Review and update
                    </Button>
                  </div>
                ) : (
                  <p className="w-note">Up to date. No update is waiting.</p>
                ))}

                <div className="mkt-actions mkt-installed-actions">
                  <Button tone="secondary" disabled={rowBusy} onClick={() => void toggle(record)}
                          pending={pendingFor(record.enabled ? 'disable' : 'enable')}
                          pendingLabel={record.enabled ? 'Disabling…' : 'Enabling…'}>
                    {record.enabled ? 'Disable' : 'Enable'}
                  </Button>
                  <Button tone="secondary" disabled={rowBusy}
                          pending={pendingFor(record.shared ? 'unshare' : 'share')}
                          pendingLabel={record.shared ? 'Stopping sharing…' : 'Sharing…'}
                          onClick={() => void toggleShare(record)}>
                    {record.shared ? 'Stop sharing' : 'Share with peers'}
                  </Button>
                  <Button tone="secondary" disabled={rowBusy}
                          onClick={() => setConfirm({ kind: 'rollback', record })}>
                    Roll back
                  </Button>
                  <Button tone="secondary" disabled={rowBusy}
                          onClick={() => { setPurgeError(''); setPurgeRecord(record); }}>
                    Purge data
                  </Button>
                  {!cannotRun && (
                    <Button tone="secondary" disabled={rowBusy}
                            onClick={() => setConfirm({ kind: 'uninstall', record })}>
                      Uninstall
                    </Button>
                  )}
                </div>
              </article>
            </li>
            );
          })}
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
        busy={busy?.id === consentRecord?.id}
        error={sheetError}
        onCancel={() => { if (busy === null) setConsentRecord(null); }}
        onConfirm={() => void acceptConsent()}
      >
        {consentRecord && visibleScopes(consentRecord.update?.scopes ?? []).length === 0 && (
          <p className="mkt-empty-inline">The staged version declares no new data access.</p>
        )}
      </ConsentSheet>

      {purgeRecord && (
        <PurgeDialog record={purgeRecord} busy={busy?.id === purgeRecord.id} error={purgeError}
                     onCancel={() => setPurgeRecord(null)} onConfirm={() => void doPurge()} />
      )}

      {confirm && (
        <div className="mkt-scrim" role="presentation">
          <div ref={confirmFocus.sheetRef} className="mkt-sheet mkt-sheet-small" role="dialog" aria-modal="true"
               aria-labelledby="mkt-confirm-title" aria-busy={busy !== null ? 'true' : undefined} tabIndex={-1}>
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
              <button ref={confirmFocus.firstRef} type="button" className="btn btn-secondary"
                      disabled={busy !== null} onClick={() => setConfirm(null)}>
                Cancel
              </button>
              <Button tone="primary" disabled={busy !== null}
                      pending={busyShown}
                      pendingLabel={confirm.kind === 'rollback' ? 'Rolling back…' : 'Uninstalling…'}
                      onClick={() => void doConfirm()}>
                {confirm.kind === 'rollback' ? 'Roll back' : 'Uninstall'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
