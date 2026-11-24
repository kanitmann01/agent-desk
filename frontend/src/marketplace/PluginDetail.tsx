// Plugin detail: the fixed content contract from T05, plus the manage
// actions T06 puts on the same page. Every action re-reads the server
// after it finishes; nothing is shown as done before the server says so.
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import Button from '../components/Button';
import { MarketApiError, getInstances, getMarket, marketErrorText, postMarket } from './client';
import { ConsentSheet } from './ConsentSheet';
import { InstanceSetupSheet, instanceFileName } from './InstanceSetupSheet';
import { MarketLink, useMarketplaceNav } from './context';
import { MarketGrid, PublisherMark, SkeletonGrid, categoryLabel, riskLabel } from './MarketGrid';
import { canNever, describeScope, formatBytes, formatDate, pilotBudget, shortDigest, visibleScopes } from './permissions';
import { SamplePreview } from './Sample';
import { SignatureChip, StatusChip } from './StatusChip';
import { useDialogFocus } from './useDialogFocus';
import type { DetailResponse, InstanceDocument, InstancesResponse, MarketDetail, InstalledSummary } from './types';

type Load =
  | { kind: 'loading' }
  | { kind: 'error'; status: number; message: string }
  | { kind: 'ready'; data: DetailResponse };

type Consent =
  | { kind: 'install' }
  | { kind: 'update' }
  | { kind: 'consent' }
  | null;

const REASONS = [
  'Spam or misleading listing',
  'Unsafe or deceptive permissions',
  'Broken sample or no sample',
  'Wrong category or tags',
  'Other',
];

/**
 * Render the page's one status line, as an alert when it reports a failure.
 *
 * Nothing is rendered while both slots are empty, so the slot leaves no gap.
 */
function ActionMessage({ error, message }: { error: string; message: string }) {
  if (!error && !message) return null;
  return (
    <p className={error ? 'mkt-error' : 'mkt-success'} role={error ? 'alert' : 'status'}>
      {error || message}
    </p>
  );
}

/**
 * Show a shortened digest with a button that copies the full value.
 *
 * A clipboard refusal leaves the idle label in place instead of claiming the
 * copy worked, and the copied state clears itself after two seconds.
 */
function Digest({ digest }: { digest: string }) {
  const [copied, setCopied] = useState(false);
  /** Copy the full digest, marking the button copied only if the clipboard accepts it. */
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(digest);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <span className="mkt-digest">
      <code title={digest}>{shortDigest(digest)}</code>
      <button type="button" className="mkt-icon-btn" onClick={copy}
              aria-label={copied ? 'Digest copied' : 'Copy digest'}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="1.8" aria-hidden="true">
          <rect x="9" y="9" width="11" height="11" rx="2" />
          <path d="M5 15H4V4h11v1" />
        </svg>
      </button>
      <span className="mkt-sr-only" role="status">{copied ? 'Digest copied' : ''}</span>
    </span>
  );
}

/**
 * Render the action row: an install button while the plugin is absent, the
 * lifecycle controls once it is installed.
 *
 * A staged update that widens permissions replaces the update button with a
 * consent review, so no widening runs unread. Every control is disabled while
 * one action is in flight.
 */
function PluginActions({
  detail, installed, busy, onInstall, onUpdate, onConsent, onAction, onPurge, onRevert, onUninstall,
}: {
  detail: MarketDetail;
  installed: InstalledSummary | null;
  busy: boolean;
  onInstall: () => void;
  onUpdate: () => void;
  onConsent: () => void;
  onAction: (action: 'enable' | 'disable' | 'retest' | 'rollback' | 'uninstall') => void;
  onPurge: () => void;
  onRevert: () => void;
  onUninstall: () => void;
}) {
  if (!installed) {
    return (
      <div className="mkt-actions">
        <Button tone="primary" disabled={busy || !detail.eligible} onClick={onInstall}>
          Install plugin
        </Button>
        {!detail.eligible && <span className="mkt-action-note">This plugin is not available under the current policy.</span>}
      </div>
    );
  }
  return (
    <div className="mkt-actions">
      {installed.pendingConsent ? (
        <>
          <Button tone="primary" disabled={busy} onClick={onConsent}>Review permission change</Button>
          <Button tone="secondary" disabled={busy} onClick={onRevert}>Decline update</Button>
        </>
      ) : installed.update ? (
        <Button tone="primary" disabled={busy} onClick={onUpdate}>
          Update to {installed.update.version}
        </Button>
      ) : (
        <span className="mkt-status mkt-tone-good"><span className="mkt-dot" aria-hidden="true" />Up to date</span>
      )}
      <Button tone="secondary" disabled={busy} onClick={() => onAction(installed.enabled ? 'disable' : 'enable')}>
        {installed.enabled ? 'Disable' : 'Enable'}
      </Button>
      <Button tone="secondary" disabled={busy} onClick={() => onAction('retest')}>Re-test</Button>
      <Button tone="secondary" disabled={busy} onClick={() => onAction('rollback')}>Roll back</Button>
      <Button tone="secondary" disabled={busy} onClick={onPurge}>Purge data</Button>
      <Button tone="secondary" disabled={busy} onClick={onUninstall}>Uninstall</Button>
    </div>
  );
}

/**
 * Render the modal that gates deleting a plugin's data behind a typed phrase.
 *
 * Confirming stays disabled until `delete-data:<id>` is typed exactly, and a
 * refusal is reported inside the dialog so the typed phrase is not lost.
 */
function PurgeDialog({ id, busy, error, onCancel, onConfirm }: {
  id: string;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const [typed, setTyped] = useState('');
  const expected = `delete-data:${id}`;
  const { sheetRef, firstRef } = useDialogFocus<HTMLInputElement>(true, onCancel);
  return (
    <div className="mkt-scrim" role="presentation">
      <div ref={sheetRef} className="mkt-sheet mkt-sheet-small" role="dialog" aria-modal="true" aria-labelledby="mkt-purge-title" tabIndex={-1}>
        <div className="mkt-sheet-head">
          <div>
            <span className="mkt-eyebrow">Destructive action</span>
            <h2 id="mkt-purge-title">Purge plugin data</h2>
          </div>
        </div>
        <div className="mkt-sheet-body">
          <p>This deletes the plugin's data folder and its install record. There is no undo.</p>
          <label className="mkt-field">
            <span>Type <code>{expected}</code> to confirm</span>
            <input ref={firstRef} value={typed} onChange={(event) => setTyped(event.target.value)}
                   autoComplete="off" spellCheck={false} />
          </label>
          {error && <p className="mkt-error" role="alert">{error}</p>}
        </div>
        <div className="mkt-sheet-foot">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn btn-primary"
                  disabled={typed !== expected || busy} onClick={onConfirm}>
            {busy ? 'Purging…' : 'Purge data'}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Render the report form for one plugin, closed until it is asked for.
 *
 * A filed report closes the form and hands its message to the page; a refusal
 * keeps the form open with the text still in it.
 */
function ReportForm({ id, onDone }: { id: string; onDone: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState(REASONS[0]);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!open) {
    return <Button tone="secondary" onClick={() => setOpen(true)}>Report this plugin</Button>;
  }
  /** File the report with the chosen reason and note, handing the outcome to the page. */
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await postMarket('/api/marketplace/report', { id, reason, note });
      setOpen(false);
      setBusy(false);
      onDone('Report filed. The marketplace operator will review it.');
    } catch (err) {
      setBusy(false);
      setError(marketErrorText(err));
    }
  };
  return (
    <form className="mkt-report" onSubmit={submit}>
      <h2>Report this plugin</h2>
      <label className="mkt-field">
        <span>Reason</span>
        <select value={reason} onChange={(event) => setReason(event.target.value)}>
          {REASONS.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <label className="mkt-field">
        <span>Note (optional)</span>
        <textarea value={note} onChange={(event) => setNote(event.target.value)} rows={3} />
      </label>
      {error && <p className="mkt-error" role="alert">{error}</p>}
      <div className="mkt-actions">
        <Button tone="primary" type="submit" disabled={busy}>{busy ? 'Filing…' : 'File report'}</Button>
        <Button tone="secondary" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </form>
  );
}

/**
 * Render one plugin's detail page, plus its actions and instances when the
 * manage view is asked for.
 *
 * A 404 becomes "plugin not found" with no retry, because retrying cannot
 * help; every other failure offers one. Each mutating action re-reads the
 * record afterwards, so the page shows what the server accepted rather than
 * what was sent.
 */
export function PluginDetailPage({ id, manage = false }: { id: string; manage?: boolean }) {
  const { navigate } = useMarketplaceNav();
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [consent, setConsent] = useState<Consent>(null);
  const [busy, setBusy] = useState(false);
  const [sheetError, setSheetError] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [purgeOpen, setPurgeOpen] = useState(false);
  const [purgeError, setPurgeError] = useState('');
  const [confirmAction, setConfirmAction] = useState<null | { action: 'rollback' | 'uninstall'; title: string; body: string }>(null);
  const confirmFocus = useDialogFocus<HTMLButtonElement>(confirmAction !== null, () => setConfirmAction(null));
  // The manage view's instance setup (T5): the list, its load error, and
  // which sheet is open. instanceAttempt re-reads after a sheet finishes.
  const [instances, setInstances] = useState<InstancesResponse | null>(null);
  const [instancesError, setInstancesError] = useState('');
  const [instanceAttempt, setInstanceAttempt] = useState(0);
  const [setupSheet, setSetupSheet] = useState<
    | { kind: 'create' }
    | { kind: 'edit'; instance: InstanceDocument }
    | null
  >(null);

  const refresh = useCallback(async () => {
    try {
      const data = await getMarket<DetailResponse>(`/api/marketplace/plugin/${encodeURIComponent(id)}`);
      setLoad({ kind: 'ready', data });
      return data;
    } catch (err) {
      const status = err instanceof MarketApiError ? err.status : 0;
      setLoad({ kind: 'error', status, message: marketErrorText(err) });
      return null;
    }
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    setLoad({ kind: 'loading' });
    getMarket<DetailResponse>(`/api/marketplace/plugin/${encodeURIComponent(id)}`)
      .then((data) => { if (!cancelled) setLoad({ kind: 'ready', data }); })
      .catch((err) => {
        if (!cancelled) {
          const status = err instanceof MarketApiError ? err.status : 0;
          setLoad({ kind: 'error', status, message: marketErrorText(err) });
        }
      });
    return () => { cancelled = true; };
  }, [id, attempt]);

  useEffect(() => {
    const current = load.kind === 'ready' ? load.data.installed : null;
    if (!manage || !current) {
      setInstances(null);
      return undefined;
    }
    let cancelled = false;
    getInstances(id)
      .then((data) => {
        if (!cancelled) {
          setInstances(data);
          setInstancesError('');
        }
      })
      .catch((err) => {
        if (!cancelled) setInstancesError(marketErrorText(err));
      });
    return () => { cancelled = true; };
  }, [id, manage, load, instanceAttempt]);

  /**
   * Run one mutating action: show its note on success or the server's message
   * on failure, then re-read the record.
   *
   * The previous note and error are cleared first, so a stale result cannot
   * sit beside a new one, and busy stays set until the re-read finishes.
   */
  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const note = await fn();
      setMessage(note);
      await refresh();
    } catch (err) {
      setError(marketErrorText(err));
    } finally {
      setBusy(false);
    }
  };

  if (load.kind === 'loading') {
    return (
      <div className="mkt-page" aria-busy="true">
        <p className="mkt-result-count">Loading plugin…</p>
        <SkeletonGrid count={3} />
      </div>
    );
  }
  if (load.kind === 'error') {
    const missing = load.status === 404;
    return (
      <div className="mkt-page">
        <header className="mkt-page-head">
          <span className="mkt-eyebrow">Plugin</span>
          <h1>{missing ? 'Plugin not found' : 'The plugin did not load'}</h1>
        </header>
        <div className="mkt-error-panel" role="alert">
          <p>{missing ? `No plugin in the catalog has the id “${id}”.` : load.message}</p>
          <div className="mkt-actions">
            {!missing && <Button tone="secondary" onClick={() => setAttempt((n) => n + 1)}>Try again</Button>}
            <MarketLink to="/marketplace" className="btn btn-secondary">Back to Discover</MarketLink>
          </div>
        </div>
      </div>
    );
  }

  const { data } = load;
  const plugin = data.plugin;
  const installed = data.installed;
  const scopes = plugin.capabilities.permissions;
  const never = canNever(plugin.capabilities);
  const title = manage ? `Manage ${plugin.name}` : plugin.name;

  /** Open the consent sheet for a first install, dropping the previous sheet's error. */
  const openInstall = () => { setSheetError(''); setConsent({ kind: 'install' }); };
  /** Open the consent sheet for a staged update, dropping the previous sheet's error. */
  const openUpdate = () => { setSheetError(''); setConsent({ kind: 'update' }); };
  /** Open the sheet that reviews a staged update's permission change, dropping the previous error. */
  const openConsent = () => { setSheetError(''); setConsent({ kind: 'consent' }); };

  const sheetScopes = consent?.kind === 'update'
    ? (installed?.update?.scopes ?? [])
    : consent?.kind === 'consent'
      ? (installed?.update?.scopes ?? [])
      : scopes;
  const sheetAdded = consent?.kind === 'update'
    ? (installed?.update?.widening ?? [])
    : consent?.kind === 'consent'
      ? (installed?.update?.widening ?? [])
      : [];
  const sheetRemoved = consent?.kind === 'update'
    ? (installed?.update?.dropping ?? [])
    : consent?.kind === 'consent'
      ? (installed?.update?.dropping ?? [])
      : [];

  /**
   * Apply whichever decision the open sheet was showing, then re-read the
   * record.
   *
   * One branch per decision: install posts the pinned version, update posts
   * the id alone, and accept posts the consent decision. A refusal stays in
   * the sheet, so the scopes being agreed to are still on screen.
   */
  const confirmConsent = async () => {
    if (!consent) return;
    const kind = consent.kind;
    const action = kind === 'install' ? 'install'
      : kind === 'update' ? 'update' : 'consent';
    setBusy(true);
    setSheetError('');
    try {
      if (action === 'install') {
        const res = await postMarket<{ id: string; version: string; status: string }>(
          '/api/marketplace/install',
          { id: plugin.id, version: plugin.version },
        );
        setMessage(`Installed ${plugin.name} ${res.version}.`);
      } else if (action === 'update') {
        const res = await postMarket<{ to: string; pendingConsent: boolean }>(
          '/api/marketplace/update', { id: plugin.id },
        );
        setMessage(res.pendingConsent
          ? `Updated to ${res.to}, but the new permission scopes still need your consent.`
          : `Updated to ${res.to}.`);
      } else {
        const res = await postMarket<{ version: string; status: string }>(
          '/api/marketplace/consent', { id: plugin.id, decision: 'accept' },
        );
        setMessage(`Update accepted. Now on ${res.version}.`);
      }
      setConsent(null);
      await refresh();
    } catch (err) {
      setSheetError(marketErrorText(err));
    } finally {
      setBusy(false);
    }
  };

  /** Reject the staged update and report the version the plugin stays on. */
  const declineUpdate = () => run(async () => {
    const res = await postMarket<{ version: string }>('/api/marketplace/consent',
      { id: plugin.id, decision: 'reject' });
    return `Update declined. Still on ${res.version}.`;
  });

  /**
   * Dispatch one lifecycle action.
   *
   * Enable, disable and re-test run immediately and report the resulting
   * state; rollback and uninstall only open their confirmation dialog, so
   * nothing irreversible happens from a single click.
   */
  const lifecycle = (action: 'enable' | 'disable' | 'retest' | 'rollback' | 'uninstall') => {
    if (action === 'rollback') { doRollback(); return; }
    if (action === 'uninstall') {
      setConfirmAction({ action: 'uninstall', title: 'Uninstall plugin',
        body: 'The plugin stops running. Its data folder is kept until you purge it.' });
      return;
    }
    run(async () => {
      const res = await postMarket<{ id: string; state?: string; status?: string }>(
        `/api/marketplace/${action}`, { id: plugin.id });
      if (action === 'retest') return 'Re-test finished. Validation status refreshed.';
      return `${plugin.name} is now ${res.state ?? (action === 'enable' ? 'enabled' : 'disabled')}.`;
    });
  };

  /** Open the confirmation dialog for a rollback without performing it. */
  const doRollback = () => {
    setConfirmAction({ action: 'rollback', title: 'Roll back plugin',
      body: 'The previous installed version becomes active. The current version stays available in history.' });
  };

  /** Roll back to the previously installed version, reporting both ends of the move. */
  const confirmRollback = () => run(async () => {
    const res = await postMarket<{ from: string; to: string }>('/api/marketplace/rollback', { id: plugin.id });
    return `Rolled back from ${res.from} to ${res.to}.`;
  });

  /** Uninstall the plugin and leave for the installed list; the data folder stays until purged. */
  const confirmUninstall = () => run(async () => {
    await postMarket('/api/marketplace/uninstall', { id: plugin.id });
    navigate('/marketplace/installed');
    return 'Uninstalled.';
  });

  /**
   * Delete the plugin's data folder and install record, then leave for the
   * installed list.
   *
   * A refusal keeps the dialog open with the server's message, since closing
   * it would throw away the typed confirmation.
   */
  const confirmPurge = async () => {
    setBusy(true);
    setPurgeError('');
    try {
      await postMarket('/api/marketplace/purge-data',
        { id: plugin.id, confirm: `delete-data:${plugin.id}` });
      setPurgeOpen(false);
      navigate('/marketplace/installed');
    } catch (err) {
      setPurgeError(marketErrorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mkt-page mkt-detail">
      <nav className="mkt-crumbs" aria-label="Breadcrumb">
        <ol>
          <li><MarketLink to="/marketplace">Marketplace</MarketLink></li>
          <li><MarketLink to={`/marketplace/category/${encodeURIComponent(plugin.category)}`}>{categoryLabel(plugin.category)}</MarketLink></li>
          <li aria-current="page">{plugin.name}</li>
        </ol>
      </nav>

      <header className="mkt-detail-head">
        <div className="mkt-detail-title">
          <span className="mkt-detail-icon"><svg width="26" height="26" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <rect x="4" y="4" width="16" height="16" rx="3" /><path d="M8 12h8M12 8v8" />
          </svg></span>
          <div>
            <span className="mkt-eyebrow">{manage ? 'Manage plugin' : categoryLabel(plugin.category)}</span>
            <h1>{title}</h1>
            <p className="mkt-detail-byline">
              {plugin.publisher} <PublisherMark verified={plugin.publisherVerified} />
              <span className="mkt-sep" aria-hidden="true">·</span>
              v{plugin.version}
              <span className="mkt-sep" aria-hidden="true">·</span>
              {plugin.license || 'No license listed'}
            </p>
          </div>
        </div>
        <PluginActions
          detail={plugin}
          installed={installed}
          busy={busy}
          onInstall={openInstall}
          onUpdate={openUpdate}
          onConsent={openConsent}
          onAction={lifecycle}
          onPurge={() => { setPurgeError(''); setPurgeOpen(true); }}
          onRevert={declineUpdate}
          onUninstall={() => lifecycle('uninstall')}
        />
      </header>

      <ActionMessage error={error} message={message} />
      {installed?.pendingConsent && (
        <p className="mkt-attention">
          An update is staged but needs your consent before it can run.
        </p>
      )}

      <p className="mkt-detail-summary">{plugin.summary}</p>

      <section className="mkt-facts" aria-label="Plugin facts">
        <div><span>Publisher</span><strong>{plugin.publisher}</strong></div>
        <div><span>Version</span><strong className="mkt-mono">v{plugin.version}</strong></div>
        <div><span>Minimum host</span><strong>{plugin.minHost || 'not stated'}</strong></div>
        <div><span>License</span><strong>{plugin.license || 'not stated'}</strong></div>
        <div><span>Digest</span><strong><Digest digest={plugin.digest} /></strong></div>
        <div><span>Signature</span><strong><SignatureChip status={plugin.signature.status} /></strong></div>
        <div><span>Risk tier</span><strong>{riskLabel(plugin.riskTier)}</strong></div>
        <div><span>Published</span><strong>{formatDate(plugin.publishedAt)}</strong></div>
      </section>

      {manage && installed && instances?.configBacked && (
        <section className="mkt-panel" aria-labelledby="mkt-instances">
          <h2 id="mkt-instances">Instances</h2>
          {instances.aliasOf && (
            <p className="w-note">
              {plugin.name} runs as the {instances.instances[0]?.name ?? 'named'} instance
              of {instances.setupPluginName}; its setup lives with that plugin, so there is
              nothing separate to configure here.
            </p>
          )}
          {instancesError && <p className="mkt-error" role="alert">{instancesError}</p>}
          {!instances.aliasOf && instances.instances.length === 0 && (
            // The finish line of the wizard walk (T6): a just-installed
            // config-backed plugin has zero instances, so Set up leads
            // the panel as the visible primary, above the empty table.
            <div className="mkt-actions">
              <Button tone="primary" onClick={() => {
                setError('');
                setSheetError('');
                setSetupSheet({ kind: 'create' });
              }}>
                Set up a new instance
              </Button>
            </div>
          )}
          <div className="mkt-table-wrap">
            <table className="rows">
              <caption className="mkt-sr-only">Instances of {plugin.name}</caption>
              <thead>
                <tr>
                  <th scope="col">Instance</th>
                  <th scope="col">File</th>
                  <th scope="col">Status</th>
                  <th scope="col">Setup</th>
                </tr>
              </thead>
              <tbody>
                {instances.instances.map((item) => (
                  <tr key={item.instanceId}>
                    <th scope="row">{item.name}</th>
                    <td className="mkt-mono">{instanceFileName(item)}</td>
                    <td>{item.confirmedAt ? 'Confirmed' : 'Needs setup'}</td>
                    <td>
                      <Button tone="secondary" onClick={() => {
                        setError('');
                        setSheetError('');
                        setSetupSheet({ kind: 'edit', instance: item });
                      }}>
                        Edit {item.name}
                      </Button>
                    </td>
                  </tr>
                ))}
                {instances.instances.length === 0 && (
                  <tr>
                    <td colSpan={4}>No instances yet. Set one up to point {plugin.name} at its data.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {!instances.aliasOf && instances.instances.length > 0 && (
            <div className="mkt-actions">
              <Button tone="primary" onClick={() => {
                setError('');
                setSheetError('');
                setSetupSheet({ kind: 'create' });
              }}>
                Set up a new instance
              </Button>
            </div>
          )}
        </section>
      )}

      <div className="mkt-detail-cols">
        <section className="mkt-panel" aria-labelledby="mkt-about">
          <h2 id="mkt-about">About this plugin</h2>
          <p>{plugin.description || plugin.summary}</p>
          {plugin.highlights.length > 0 && (
            <ul className="mkt-highlights">
              {plugin.highlights.map((line) => <li key={line}>{line}</li>)}
            </ul>
          )}
          {plugin.homepage && (
            <p className="w-note">
              Homepage: <a href={plugin.homepage} target="_blank" rel="noreferrer noopener">{plugin.homepage}</a>
            </p>
          )}
          <dl className="mkt-proof">
            <dt>Signing key</dt>
            <dd className="mkt-mono">{plugin.signature.fingerprint || 'none'}</dd>
            <dt>Signature status</dt>
            <dd>{plugin.signature.status || 'missing'}{plugin.signature.signedAt ? ` · signed ${formatDate(plugin.signature.signedAt)}` : ''}</dd>
            <dt>Provenance</dt>
            <dd>{plugin.provenance?.builder || 'Unknown builder'}{plugin.provenance?.sourceCommit ? ` · ${plugin.provenance.sourceCommit.slice(0, 10)}` : ''}</dd>
            <dt>Source</dt>
            <dd>{plugin.source}</dd>
          </dl>
        </section>

        <section className="mkt-panel" aria-labelledby="mkt-perms">
          <h2 id="mkt-perms">What it can use</h2>
          {visibleScopes(scopes).length === 0 ? (
            <p className="mkt-empty-inline">It asks for no data access.</p>
          ) : (
            <ul className="mkt-scope-list">
              {visibleScopes(scopes).map((scope) => {
                const meaning = describeScope(scope);
                return (
                  <li key={scope}>
                    <span className="mkt-scope-sentence">{meaning.sentence}</span>
                    <span className="w-note">You control this under {meaning.setting}.</span>
                  </li>
                );
              })}
            </ul>
          )}
          <h3>What it can never do</h3>
          <ul className="mkt-never-list">
            {never.map((line) => <li key={line}>{line}</li>)}
          </ul>
          <p className="w-note mkt-cap-note">
            Data sources: {plugin.capabilities.sources.length > 0
              ? plugin.capabilities.sources.join(', ')
              : 'none declared'}.
          </p>
        </section>
      </div>

      <SamplePreview sample={data.sample} title={plugin.name} />

      <section className="mkt-panel" aria-labelledby="mkt-validation">
        <h2 id="mkt-validation">Validator report</h2>
        <div className="mkt-validation-row">
          <span className={`mkt-status mkt-tone-${plugin.validation.ok === true ? 'good' : plugin.validation.ok === false ? 'bad' : 'neutral'}`}>
            <span className="mkt-dot" aria-hidden="true" />
            {plugin.validation.ok === true ? 'Passed' : plugin.validation.ok === false ? 'Failed' : 'Not checked'}
          </span>
          <span className="w-note">Checked {formatDate(plugin.validation.checkedAt)}</span>
          {installed && <Button tone="secondary" disabled={busy} onClick={() => lifecycle('retest')}>Re-run validator</Button>}
        </div>
        {plugin.validation.failures.length > 0 && (
          <ul className="mkt-failures">
            {plugin.validation.failures.map((failure) => (
              <li key={failure.code}><code>{failure.code}</code> {failure.message}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="mkt-panel" aria-labelledby="mkt-versions">
        <h2 id="mkt-versions">Version history</h2>
        <div className="mkt-table-wrap">
          <table className="rows">
            <caption className="mkt-sr-only">Versions of {plugin.name}</caption>
            <thead>
              <tr><th scope="col">Version</th><th scope="col">Digest</th><th scope="col">Change</th><th scope="col">Status</th></tr>
            </thead>
            <tbody>
              {data.versions.map((version) => (
                <tr key={version.version}>
                  <th scope="row" className="mkt-mono">v{version.version}</th>
                  <td className="mkt-mono">{shortDigest(version.digest)}</td>
                  <td>{version.version === plugin.version ? (plugin.changelog.text || 'Current release') : 'See release notes'}</td>
                  <td>{version.yanked ? <span className="mkt-status mkt-tone-warn"><span className="mkt-dot" aria-hidden="true" />Yanked</span> : 'Available'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="w-note">
          Permission changes between versions appear in the consent sheet before an update runs.
        </p>
      </section>

      {data.alternatives.length > 0 && (
        <section className="mkt-panel" aria-labelledby="mkt-alternatives">
          <h2 id="mkt-alternatives">Alternatives in {categoryLabel(plugin.category)}</h2>
          <MarketGrid cards={data.alternatives} />
        </section>
      )}

      {installed && (
        <section className="mkt-panel" aria-labelledby="mkt-install-state">
          <h2 id="mkt-install-state">Installed state</h2>
          <div className="mkt-facts">
            <div><span>Status</span><strong><StatusChip status={installed.status.status} /></strong></div>
            <div><span>Pinned version</span><strong className="mkt-mono">v{installed.pinned.version}</strong></div>
            <div><span>Pinned digest</span><strong className="mkt-mono">{shortDigest(installed.pinned.sha256)}</strong></div>
            <div><span>Pilot</span><strong>{pilotBudget(installed.pilot)}</strong></div>
            <div><span>Data folder</span><strong>{formatBytes(installed.dataDirSize)}</strong></div>
            <div><span>Shared with peers</span><strong>{installed.shared ? 'Yes' : 'No'}</strong></div>
          </div>
          {installed.status.cause && <p className="mkt-attention">{installed.status.cause}</p>}
        </section>
      )}

      <section className="mkt-panel" aria-labelledby="mkt-report">
        <h2 id="mkt-report">Something wrong?</h2>
        <ReportForm id={plugin.id} onDone={setMessage} />
      </section>

      <ConsentSheet
        open={consent !== null}
        title={consent?.kind === 'install' ? `Install ${plugin.name}`
          : consent?.kind === 'update' ? `Update ${plugin.name}` : 'Review permission change'}
        intro={consent?.kind === 'install'
          ? `Installing ${plugin.name} v${plugin.version} lets it use the scopes below while it runs.`
          : `The staged update changes what ${plugin.name} can reach. Review the new scopes before it runs.`}
        scopes={sheetScopes}
        addedScopes={sheetAdded}
        removedScopes={sheetRemoved}
        canNever={never}
        confirmLabel={consent?.kind === 'install' ? 'Install plugin'
          : consent?.kind === 'update' ? 'Update plugin' : 'Accept update'}
        busy={busy}
        error={sheetError}
        onCancel={() => { if (!busy) setConsent(null); }}
        onConfirm={confirmConsent}
      />

      {setupSheet && instances && (
        <InstanceSetupSheet
          title={setupSheet.kind === 'create' ? 'Set up an instance' : `Edit ${setupSheet.instance.name}`}
          pluginName={plugin.name}
          setupPluginId={instances.setupPluginId}
          target={setupSheet.kind === 'create'
            ? { mode: 'create' }
            : { mode: 'edit', instance: setupSheet.instance }}
          onCancel={() => setSetupSheet(null)}
          onChanged={() => setInstanceAttempt((n) => n + 1)}
          onDone={(note) => {
            setSetupSheet(null);
            setMessage(note);
            setInstanceAttempt((n) => n + 1);
          }}
        />
      )}

      {purgeOpen && (
        <PurgeDialog id={plugin.id} busy={busy} error={purgeError}
                     onCancel={() => setPurgeOpen(false)} onConfirm={confirmPurge} />
      )}

      {confirmAction && (
        <div className="mkt-scrim" role="presentation">
          <div ref={confirmFocus.sheetRef} className="mkt-sheet mkt-sheet-small" role="dialog" aria-modal="true"
               aria-labelledby="mkt-confirm-title" tabIndex={-1}>
            <div className="mkt-sheet-head">
              <h2 id="mkt-confirm-title">{confirmAction.title}</h2>
            </div>
            <div className="mkt-sheet-body"><p>{confirmAction.body}</p></div>
            <div className="mkt-sheet-foot">
              <button ref={confirmFocus.firstRef} type="button" className="btn btn-secondary" onClick={() => setConfirmAction(null)}>Cancel</button>
              <button type="button" className="btn btn-primary" disabled={busy}
                      onClick={() => {
                        const action = confirmAction.action;
                        setConfirmAction(null);
                        if (action === 'rollback') confirmRollback();
                        else confirmUninstall();
                      }}>
                {busy ? 'Working…' : confirmAction.action === 'rollback' ? 'Roll back' : 'Uninstall'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
