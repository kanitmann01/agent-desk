import { useCallback, useEffect, useState, type ChangeEvent } from 'react';
import Button from '../components/Button';
import { getMarket, MarketApiError, marketErrorText, postMarket } from './client';
import type {
  AdminSnapshot,
  PendingPublication,
  PolicyDiffEntry,
  PolicyImportResult,
} from './types';
import './admin-trust.css';

function listText(values: string[], empty = 'Any'): string {
  return values.length ? values.join(', ') : empty;
}

function valueText(value: unknown): string {
  if (value === null || value === undefined) return 'none';
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'none';
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function pendingLabel(item: PendingPublication): string {
  return item.pluginId || item.id;
}

function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
    reader.onerror = () => reject(reader.error ?? new Error('the file could not be read'));
    reader.readAsText(file);
  });
}

function DiffTable({ rows }: { rows: PolicyDiffEntry[] }) {
  if (rows.length === 0) {
    return (
      <p className="mkt-empty-inline">
        No policy field changes. Confirming still pins the signer fingerprint and advances the
        revocation epoch.
      </p>
    );
  }
  return (
    <table className="mkt-diff">
      <caption className="mkt-sr-only">Policy fields changed by this signed bundle</caption>
      <thead>
        <tr>
          <th scope="col">Field</th>
          <th scope="col">Active policy</th>
          <th scope="col">Imported bundle</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.field}>
            <th scope="row">{row.field}</th>
            <td><code>{valueText(row.before)}</code></td>
            <td><code>{valueText(row.after)}</code></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function AdminPage() {
  const [snapshot, setSnapshot] = useState<AdminSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [disabled, setDisabled] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState('');
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [killId, setKillId] = useState('');
  const [bundle, setBundle] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<PolicyImportResult | null>(null);
  const [importError, setImportError] = useState('');
  const [applying, setApplying] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await getMarket<AdminSnapshot>('/api/marketplace/admin');
      setSnapshot(data);
      setDisabled(false);
      setError('');
    } catch (err) {
      if (err instanceof MarketApiError && err.code === 'admin:disabled') {
        setDisabled(true);
        setSnapshot(null);
      } else {
        setError(marketErrorText(err));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setImportError('');
    setPreview(null);
    setBundle(null);
    setNotice('');
    if (!file) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(await readFileText(file));
    } catch {
      setImportError('That file is not valid JSON. Export the signed bundle again.');
      return;
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      setImportError('The bundle must be a JSON object.');
      return;
    }
    setBundle(parsed as Record<string, unknown>);
    try {
      const result = await postMarket<PolicyImportResult>('/api/marketplace/policy/import', {
        bundle: parsed,
        confirm: false,
      });
      setPreview(result);
    } catch (err) {
      setImportError(marketErrorText(err));
    }
  };

  const confirmImport = async () => {
    if (!bundle) return;
    setApplying(true);
    setImportError('');
    try {
      await postMarket<PolicyImportResult>('/api/marketplace/policy/import', {
        bundle,
        confirm: true,
      });
      setPreview(null);
      setBundle(null);
      setNotice('Signed policy applied. policy.json is now the file of record.');
      await load();
    } catch (err) {
      setImportError(marketErrorText(err));
    } finally {
      setApplying(false);
    }
  };

  const decide = async (item: PendingPublication, action: 'approve' | 'reject') => {
    const label = pendingLabel(item);
    const reason = (reasons[item.id] ?? '').trim();
    if (action === 'reject' && !reason) return;
    setBusy(item.id);
    setActionError('');
    setNotice('');
    try {
      await postMarket(
        `/api/marketplace/admin/publications/${encodeURIComponent(item.id)}/${action}`,
        action === 'reject' ? { reason } : {},
      );
      setNotice(
        action === 'approve'
          ? `Approved ${label}. It is now in the organization catalog.`
          : `Rejected ${label}. The publication was removed.`,
      );
      if (action === 'reject') {
        setReasons((current) => {
          const next = { ...current };
          delete next[item.id];
          return next;
        });
      }
      await load();
    } catch (err) {
      setActionError(marketErrorText(err));
    } finally {
      setBusy('');
    }
  };

  const setKill = async (pluginId: string, enabled: boolean) => {
    setBusy(`kill:${pluginId}`);
    setActionError('');
    setNotice('');
    try {
      await postMarket('/api/marketplace/admin/kill-switch', { pluginId, enabled });
      setNotice(
        enabled
          ? `${pluginId} is blocked. It is not eligible to run.`
          : `${pluginId} is no longer blocked by the kill switch.`,
      );
      if (enabled) setKillId('');
      await load();
    } catch (err) {
      setActionError(marketErrorText(err));
    } finally {
      setBusy('');
    }
  };

  if (disabled) {
    return (
      <div className="mkt-page">
        <header className="mkt-page-head">
          <span className="mkt-eyebrow">Enterprise policy</span>
          <h1>Marketplace admin</h1>
          <p className="mkt-lede">
            Governance for this desk: the signed policy, pending publications and the audit log.
          </p>
        </header>
        <section className="mkt-panel" aria-labelledby="mkt-admin-off">
          <h2 id="mkt-admin-off">Admin mode is off</h2>
          <p>
            The admin surface is disabled on this desk. Set <code>AGENTDESK_MARKETPLACE_ADMIN=1</code>{' '}
            in the environment that starts Nexuus Bot, then reload this page.
          </p>
          <p className="w-note">
            Nothing is served while admin mode is off: no snapshot, no mutation and no audit export.
            A signed-in session is still required when it is on.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="mkt-page">
      <header className="mkt-page-head">
        <span className="mkt-eyebrow">Enterprise policy</span>
        <h1>Marketplace admin</h1>
        <p className="mkt-lede">
          The signed policy file is the record. This page reads posture and pending work, and
          imports a new bundle only after showing you the diff and a second confirmation.
        </p>
      </header>

      {loading && !snapshot && (
        <section className="mkt-panel">
          <p role="status">Loading the governance snapshot…</p>
        </section>
      )}

      {error && (
        <section className="mkt-error-panel" role="alert">
          <h2>The admin snapshot could not be loaded</h2>
          <p>{error}</p>
          <Button onClick={() => void load()}>Try again</Button>
        </section>
      )}

      {notice && <p className="mkt-success" role="status">{notice}</p>}
      {actionError && <p className="mkt-error" role="alert">{actionError}</p>}

      {snapshot && (
        <div className="mkt-admin-grid">
          <section className="mkt-panel" aria-labelledby="mkt-posture">
            <h2 id="mkt-posture">Posture</h2>
            <dl className="mkt-facts">
              <div><span>Mode</span><strong>{snapshot.posture.mode}</strong></div>
              <div><span>Risk ceiling</span><strong>{snapshot.posture.riskCeiling}</strong></div>
              <div>
                <span>Signatures required</span>
                <strong>{snapshot.posture.requireSignatures ? 'Yes' : 'No'}</strong>
              </div>
              <div>
                <span>Allowed publishers</span>
                <strong>{listText(snapshot.posture.allowedPublishers)}</strong>
              </div>
              <div>
                <span>Allowed categories</span>
                <strong>{listText(snapshot.posture.allowedCategories)}</strong>
              </div>
              <div>
                <span>Network allowlist</span>
                <strong>{listText(snapshot.posture.networkAllowlist)}</strong>
              </div>
              <div>
                <span>Enabled sources</span>
                <strong>{snapshot.posture.enabledSources.length} sources</strong>
              </div>
              <div><span>Catalog source</span><strong>{snapshot.catalogSource}</strong></div>
              <div><span>Audit events</span><strong>{snapshot.auditEvents}</strong></div>
            </dl>
          </section>

          <section className="mkt-panel" aria-labelledby="mkt-anchor">
            <h2 id="mkt-anchor">Anchor and policy verification</h2>
            <dl className="mkt-proof">
              <dt>Anchor epoch</dt>
              <dd>{snapshot.anchor.epoch}</dd>
              <dt>Pinned fingerprints</dt>
              <dd>
                {snapshot.anchor.fingerprints.length === 0 ? (
                  'No signing key is pinned yet'
                ) : (
                  snapshot.anchor.fingerprints.map((fingerprint) => (
                    <code className="mkt-fingerprint" key={fingerprint}>{fingerprint}</code>
                  ))
                )}
              </dd>
              <dt>Policy signature</dt>
              <dd>{snapshot.policy.signatureStatus}</dd>
              <dt>Signer fingerprint</dt>
              <dd>
                {snapshot.policy.signerFingerprint ? (
                  <code className="mkt-fingerprint">{snapshot.policy.signerFingerprint}</code>
                ) : (
                  'Unsigned local policy'
                )}
              </dd>
              <dt>Policy epoch</dt>
              <dd>{snapshot.policy.epoch}</dd>
              <dt>Expires</dt>
              <dd>{snapshot.policy.expiresAt ?? 'No expiry recorded'}</dd>
            </dl>
            {snapshot.policy.warning && (
              <p className="mkt-policy-warning" role="status">{snapshot.policy.warning}</p>
            )}
          </section>

          <section className="mkt-panel mkt-admin-wide" aria-labelledby="mkt-import">
            <h2 id="mkt-import">Import a signed policy</h2>
            <p>
              Choose the signed JSON bundle. The diff is computed against the policy active right
              now; nothing is written until you press the second button.
            </p>
            <div className="mkt-field">
              <label htmlFor="mkt-policy-file">Signed policy bundle file</label>
              <input
                id="mkt-policy-file"
                type="file"
                accept="application/json,.json"
                onChange={(event) => void onFile(event)}
              />
              <small>Verification runs on import. A rejected bundle leaves the curated policy in place.</small>
            </div>
            {importError && <p className="mkt-error" role="alert">{importError}</p>}
            {preview && (
              <div className="mkt-import-preview">
                <h3>Changes in this bundle</h3>
                <DiffTable rows={preview.diff} />
                <p className="w-note">
                  Verification: {preview.verification.signatureStatus}, epoch{' '}
                  {preview.verification.epoch}, signer{' '}
                  {preview.verification.signerFingerprint ?? 'not recorded'}.
                </p>
                {preview.verification.warning && (
                  <p className="mkt-policy-warning" role="status">{preview.verification.warning}</p>
                )}
                <div className="mkt-actions">
                  <Button tone="primary" onClick={() => void confirmImport()} disabled={applying}>
                    {applying ? 'Applying…' : 'Apply signed policy'}
                  </Button>
                </div>
              </div>
            )}
          </section>

          <section className="mkt-panel" aria-labelledby="mkt-kill-switch">
            <h2 id="mkt-kill-switch">Kill switch</h2>
            <p>Blocking a plugin makes it ineligible everywhere, even when a signed policy allows it.</p>
            <ul className="mkt-trust-list">
              {snapshot.posture.killSwitch.length === 0 ? (
                <li>No plugin is blocked.</li>
              ) : (
                snapshot.posture.killSwitch.map((pluginId) => (
                  <li key={pluginId} className="mkt-admin-row">
                    <code className="mkt-fingerprint">{pluginId}</code>
                    <Button
                      onClick={() => void setKill(pluginId, false)}
                      disabled={busy === `kill:${pluginId}`}
                    >
                      Restore {pluginId}
                    </Button>
                  </li>
                ))
              )}
            </ul>
            <form
              className="mkt-actions"
              onSubmit={(event) => {
                event.preventDefault();
                const id = killId.trim();
                if (id) void setKill(id, true);
              }}
            >
              <div className="mkt-field">
                <label htmlFor="mkt-kill-id">Plugin id to block</label>
                <input
                  id="mkt-kill-id"
                  value={killId}
                  onChange={(event) => setKillId(event.target.value)}
                  placeholder="sample-plugin"
                />
              </div>
              <Button tone="primary" type="submit" disabled={!killId.trim() || busy === `kill:${killId.trim()}`}>
                Block plugin
              </Button>
            </form>
          </section>

          <section className="mkt-panel" aria-labelledby="mkt-revoked">
            <h2 id="mkt-revoked">Revoked publishers and releases</h2>
            {snapshot.revoked.length === 0 ? (
              <p className="mkt-empty-inline">
                Nothing is revoked under the current revocation epoch.
              </p>
            ) : (
              <div className="mkt-table-wrap">
                <table>
                  <caption className="mkt-sr-only">Revoked marketplace entries</caption>
                  <thead>
                    <tr><th scope="col">Plugin</th><th scope="col">Version</th><th scope="col">Action</th><th scope="col">Reason</th></tr>
                  </thead>
                  <tbody>
                    {snapshot.revoked.map((entry) => (
                      <tr key={`${entry.id}@${entry.version}:${entry.action}`}>
                        <th scope="row">{entry.id}</th>
                        <td>{entry.version || 'all versions'}</td>
                        <td>{entry.action}</td>
                        <td>{entry.reason || 'No reason recorded'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="mkt-panel mkt-admin-wide" aria-labelledby="mkt-pending">
            <h2 id="mkt-pending">Pending publications</h2>
            {snapshot.pending.length === 0 ? (
              <p className="mkt-empty-inline">No publications are waiting for review.</p>
            ) : (
              <ul className="mkt-installed">
                {snapshot.pending.map((item) => {
                  const label = pendingLabel(item);
                  const reason = reasons[item.id] ?? '';
                  return (
                    <li className="mkt-installed-card" key={item.id}>
                      <div className="mkt-installed-head">
                        <div>
                          <h3>{label} <span className="mkt-mono">{item.version}</span></h3>
                          <p className="mkt-installed-meta">
                            {item.publisher} / submitted {item.submittedAt} / id {item.id}
                          </p>
                        </div>
                      </div>
                      <p>{item.changelog || 'No changelog was provided.'}</p>
                      <div className="mkt-field">
                        <label htmlFor={`mkt-reason-${item.id}`}>Rejection reason for {label}</label>
                        <input
                          id={`mkt-reason-${item.id}`}
                          value={reason}
                          onChange={(event) =>
                            setReasons((current) => ({ ...current, [item.id]: event.target.value }))
                          }
                          placeholder="Why is this release rejected?"
                        />
                      </div>
                      <div className="mkt-actions">
                        <Button
                          tone="primary"
                          onClick={() => void decide(item, 'approve')}
                          disabled={busy === item.id}
                        >
                          Approve {label}
                        </Button>
                        <Button
                          onClick={() => void decide(item, 'reject')}
                          disabled={busy === item.id || !reason.trim()}
                        >
                          Reject {label}
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="mkt-panel mkt-admin-wide" aria-labelledby="mkt-inventory">
            <h2 id="mkt-inventory">Inventory</h2>
            {snapshot.inventory.length === 0 ? (
              <p className="mkt-empty-inline">No plugins are installed.</p>
            ) : (
              <div className="mkt-table-wrap">
                <table>
                  <caption className="mkt-sr-only">Installed plugins and their eligibility</caption>
                  <thead>
                    <tr>
                      <th scope="col">Plugin</th>
                      <th scope="col">Version</th>
                      <th scope="col">Publisher</th>
                      <th scope="col">Digest</th>
                      <th scope="col">Enabled</th>
                      <th scope="col">Eligible</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.inventory.map((item) => (
                      <tr key={`${item.id}@${item.version}`}>
                        <th scope="row">{item.id}</th>
                        <td>{item.version}</td>
                        <td>{item.publisher}</td>
                        <td><code title={item.digest}>{item.digest ? item.digest.slice(0, 12) : 'none'}</code></td>
                        <td>{item.enabled ? 'Yes' : 'No'}</td>
                        <td>
                          {item.eligible
                            ? 'Yes'
                            : `No (${(item.reasons ?? []).map((reason) => reason.code).join(', ') || 'policy'})`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="mkt-panel mkt-admin-wide" aria-labelledby="mkt-audit">
            <h2 id="mkt-audit">Audit log</h2>
            <p>
              Events stay on this machine. The export is JSONL, one event per line, with no message
              bodies, changelogs or rejection reasons.
            </p>
            <div className="mkt-actions">
              <a
                className="btn btn-secondary"
                href="/api/marketplace/audit/export"
                download="marketplace-audit.jsonl"
              >
                Export audit log (JSONL)
              </a>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
