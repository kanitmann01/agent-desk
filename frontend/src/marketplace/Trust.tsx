import { useCallback, useEffect, useState } from 'react';
import Button from '../components/Button';
import { getMarket, marketErrorText } from './client';
import { MarketLink } from './context';
import type { TrustSnapshot } from './types';
import './admin-trust.css';

/**
 * Render the trust center: the anchor, the policy signature, the last
 * validator run, and the promises that bound a plugin.
 *
 * The snapshot is fetched once on mount. A failed fetch keeps the page on the
 * server's message with a retry; a validator run with no recorded time reads
 * as never checked rather than as a pass.
 */
export default function TrustPage() {
  const [snapshot, setSnapshot] = useState<TrustSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const data = await getMarket<TrustSnapshot>('/api/marketplace/trust');
      setSnapshot(data);
      setError('');
    } catch (err) {
      setError(marketErrorText(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mkt-page">
      <header className="mkt-page-head">
        <span className="mkt-eyebrow">Trust</span>
        <h1>Trust center</h1>
        <p className="mkt-lede">
          What this marketplace verifies before a plugin is eligible, what the signed policy pins,
          and what the product will never do on this desk.
        </p>
      </header>

      {loading && !snapshot && (
        <section className="mkt-panel">
          <p role="status">Loading the trust snapshot…</p>
        </section>
      )}

      {error && (
        <section className="mkt-error-panel" role="alert">
          <h2>The trust snapshot could not be loaded</h2>
          <p>{error}</p>
          <Button onClick={() => void load()}>Try again</Button>
        </section>
      )}

      {snapshot && (
        <div className="mkt-admin-grid">
          <section className="mkt-panel" aria-labelledby="mkt-trust-anchor">
            <h2 id="mkt-trust-anchor">Anchor</h2>
            <dl className="mkt-proof">
              <dt>Revocation epoch</dt>
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
            </dl>
            <p className="w-note">
              The anchor records the highest revocation epoch this desk has seen. A bundle that
              claims an older epoch is rejected instead of rolling protection back.
            </p>
          </section>

          <section className="mkt-panel" aria-labelledby="mkt-trust-policy">
            <h2 id="mkt-trust-policy">Policy signature</h2>
            <dl className="mkt-proof">
              <dt>Status</dt>
              <dd>{snapshot.policy.signatureStatus}</dd>
              <dt>Mode</dt>
              <dd>{snapshot.policy.mode}</dd>
              <dt>Source</dt>
              <dd>{snapshot.policy.source}</dd>
              <dt>Signer fingerprint</dt>
              <dd>
                {snapshot.policy.signerFingerprint ? (
                  <code className="mkt-fingerprint">{snapshot.policy.signerFingerprint}</code>
                ) : (
                  'Unsigned local policy'
                )}
              </dd>
              <dt>Policy epoch</dt>
              <dd>{snapshot.policy.epoch ? snapshot.policy.epoch : 'Not recorded'}</dd>
              <dt>Expires</dt>
              <dd>{snapshot.policy.expiresAt ?? 'No expiry recorded'}</dd>
            </dl>
            {snapshot.policy.warning && (
              <p className="mkt-policy-warning" role="status">{snapshot.policy.warning}</p>
            )}
          </section>

          <section className="mkt-panel" aria-labelledby="mkt-trust-validator">
            <h2 id="mkt-trust-validator">Last validator run</h2>
            {snapshot.lastValidatorRun.at === null ? (
              <p className="mkt-empty-inline">
                No validator run has been recorded yet. This is not a pass; nothing has been checked
                on this desk so far.
              </p>
            ) : (
              <dl className="mkt-proof">
                <dt>When</dt>
                <dd>{snapshot.lastValidatorRun.at}</dd>
                <dt>Result</dt>
                <dd>{snapshot.lastValidatorRun.ok ? 'Passed' : 'Failed'}</dd>
                <dt>Scope</dt>
                <dd>{snapshot.lastValidatorRun.scope ?? 'Not recorded'}</dd>
                <dt>Failures</dt>
                <dd>
                  {(snapshot.lastValidatorRun.failures ?? []).length === 0 ? (
                    'None'
                  ) : (
                    <ul className="mkt-failures">
                      {snapshot.lastValidatorRun.failures.map((failure) => (
                        <li key={failure.code}>
                          <code>{failure.code}</code> {failure.message}
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
              </dl>
            )}
          </section>

          <section className="mkt-panel" aria-labelledby="mkt-trust-report">
            <h2 id="mkt-trust-report">How to report a problem</h2>
            <p>
              Open the plugin you installed and use its Report action. Reports stay local, are
              reviewed here and are never sent anywhere automatically.
            </p>
            <div className="mkt-actions">
              <MarketLink className="btn btn-secondary" to="/marketplace/installed">
                Open installed plugins
              </MarketLink>
            </div>
            <p className="w-note">
              Local report index: <code>{snapshot.reportPath}</code>
            </p>
          </section>

          <section className="mkt-panel mkt-admin-wide" aria-labelledby="mkt-trust-guards">
            <h2 id="mkt-trust-guards">What is checked before a plugin can run</h2>
            <ul className="mkt-trust-list">
              {snapshot.guarantees.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </section>

          <section className="mkt-panel mkt-admin-wide" aria-labelledby="mkt-trust-never">
            <h2 id="mkt-trust-never">What can never happen</h2>
            <ul className="mkt-never-list">
              {snapshot.cannotHappen.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}
