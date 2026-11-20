// A pack is metadata: one list of members, one consent sheet, one POST.
// The server installs all of them or none and names the blocked member.
import { useEffect, useState } from 'react';
import Button from '../components/Button';
import EmptyState, { ICON_SHEET } from '../components/EmptyState';
import { MarketApiError, getMarket, marketErrorText, postMarket } from './client';
import { ConsentSheet } from './ConsentSheet';
import { MarketLink } from './context';
import { PluginIcon } from './icons';
import { PublisherMark, SkeletonGrid } from './MarketGrid';
import { canNeverFromScopes, visibleScopes } from './permissions';
import type { Pack, PacksResponse } from './types';

type Load =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; pack: Pack | null; packCount: number };

export function PackPage({ id }: { id: string }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoad({ kind: 'loading' });
    getMarket<PacksResponse>('/api/marketplace/packs')
      .then((data) => {
        if (cancelled) return;
        setLoad({
          kind: 'ready',
          pack: data.packs.find((pack) => pack.id === id) ?? null,
          packCount: data.packs.length,
        });
      })
      .catch((err) => {
        if (!cancelled) setLoad({ kind: 'error', message: marketErrorText(err) });
      });
    return () => { cancelled = true; };
  }, [id, attempt]);

  if (load.kind === 'loading') {
    return (
      <div className="mkt-page" aria-busy="true">
        <p className="mkt-result-count">Loading pack…</p>
        <SkeletonGrid count={3} />
      </div>
    );
  }
  if (load.kind === 'error') {
    return (
      <div className="mkt-page">
        <h1>The pack did not load</h1>
        <div className="mkt-error-panel" role="alert">
          <p>{load.message}</p>
          <Button tone="secondary" onClick={() => setAttempt((n) => n + 1)}>Try again</Button>
        </div>
      </div>
    );
  }
  if (load.packCount === 0) {
    return (
      <div className="mkt-page">
        <nav className="mkt-crumbs" aria-label="Breadcrumb">
          <ol>
            <li><MarketLink to="/marketplace">Marketplace</MarketLink></li>
            <li aria-current="page">Packs</li>
          </ol>
        </nav>
        <header className="mkt-page-head">
          <span className="mkt-eyebrow">Marketplace</span>
          <h1>Packs are no longer offered</h1>
          <p className="mkt-lede">
            Every plugin installs on its own, with its own permission sheet.
          </p>
        </header>
        <EmptyState
          icon={ICON_SHEET}
          action={<MarketLink className="btn btn-secondary" to="/marketplace">Browse plugins</MarketLink>}
        >
          <span>No packs are published.</span>
          <span className="w-note mkt-empty-line">
            The two plugins this desk still ships are on Discover.
          </span>
        </EmptyState>
      </div>
    );
  }
  const pack = load.pack;
  if (!pack) {
    return (
      <div className="mkt-page">
        <h1>Pack not found</h1>
        <p>No pack has the id “{id}”.</p>
        <MarketLink className="btn btn-secondary" to="/marketplace">Back to Discover</MarketLink>
      </div>
    );
  }

  const scopes = Array.from(new Set(pack.members.flatMap((member) => member.scopes))).sort();
  const blocked = pack.blockedMember;

  const install = async () => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const res = await postMarket<{ id: string; installed: { id: string; version: string }[]; alreadyInstalled: string[] }>(
        '/api/marketplace/packs/install', { id: pack.id });
      const count = res.installed.length;
      setMessage(count === 0
        ? 'Every plugin in this pack was already installed.'
        : `Installed ${count} plugin${count === 1 ? '' : 's'} from ${pack.name}.`);
      setSheetOpen(false);
    } catch (err) {
      if (err instanceof MarketApiError && err.details.blockedMember) {
        setError(`${pack.name} was not installed: ${String(err.details.blockedMember)} is blocked. ${err.message}`);
      } else {
        setError(marketErrorText(err));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mkt-page">
      <nav className="mkt-crumbs" aria-label="Breadcrumb">
        <ol>
          <li><MarketLink to="/marketplace">Marketplace</MarketLink></li>
          <li aria-current="page">{pack.name}</li>
        </ol>
      </nav>
      <header className="mkt-page-head mkt-pack-head">
        <span className="mkt-pack-icon"><PluginIcon name={pack.icon} size={28} /></span>
        <div>
          <span className="mkt-eyebrow">Pack · {pack.audience}</span>
          <h1>{pack.name}</h1>
          <p className="mkt-lede">{pack.summary}</p>
        </div>
      </header>

      {blocked && (
        <p className="mkt-attention" role="status">
          <strong>{blocked}</strong> is blocked by the current policy, so this pack cannot be installed.
          {pack.blockedReason ? ` ${pack.blockedReason}` : ''}
        </p>
      )}
      {error && <p className="mkt-error" role="alert">{error}</p>}
      {message && <p className="mkt-success" role="status">{message}</p>}

      <div className="mkt-pack-actions">
        <Button tone="primary" disabled={busy} onClick={() => setSheetOpen(true)}>
          Review and install all {pack.members.length} plugins
        </Button>
        <span className="w-note">One consent sheet covers every member scope. If one member is blocked, nothing installs.</span>
      </div>

      <section className="mkt-panel" aria-labelledby="mkt-pack-members">
        <h2 id="mkt-pack-members">What is in this pack</h2>
        <ul className="mkt-pack-members" role="list">
          {pack.members.map((member) => (
            <li key={member.id} className={member.eligible ? '' : 'is-blocked'}>
              <div>
                <MarketLink to={`/marketplace/plugin/${encodeURIComponent(member.id)}`} className="mkt-member-name">
                  {member.name}
                </MarketLink>
                <span className="mkt-mono w-note">v{member.version}</span>
                {!member.eligible && (
                  <span className="mkt-ineligible-label">
                    {' '}Blocked: {member.ineligibleReasons[0]?.message || 'policy denied'}
                  </span>
                )}
              </div>
              <span className="w-note">
                {visibleScopes(member.scopes).length === 0
                  ? 'No data access'
                  : `${visibleScopes(member.scopes).length} scope${visibleScopes(member.scopes).length === 1 ? '' : 's'}`}
              </span>
            </li>
          ))}
        </ul>
        {pack.excluded.length > 0 && (
          <div className="mkt-excluded">
            <h3>Deliberately excluded</h3>
            <ul>
              {pack.excluded.map((item) => <li key={item.id}><strong>{item.id}</strong>: {item.reason}</li>)}
            </ul>
          </div>
        )}
      </section>

      <ConsentSheet
        open={sheetOpen}
        title={`Install ${pack.name}`}
        intro={`This installs ${pack.members.length} plugins together. All or none: the server installs nothing if one member is blocked.`}
        scopes={scopes}
        canNever={canNeverFromScopes(scopes)}
        confirmLabel={`Install all ${pack.members.length}`}
        busy={busy}
        error={error}
        onCancel={() => { if (!busy) setSheetOpen(false); }}
        onConfirm={install}
      />

      <section className="mkt-panel">
        <h2>Publisher verification</h2>
        <p className="w-note">
          Each member carries its own publisher proof on its detail page. A pack does not vouch for its members.
        </p>
        <ul className="mkt-pack-proofs">
          {Array.from(new Set(pack.plugins.map((plugin) => plugin.publisher))).map((publisher) => {
            const card = pack.plugins.find((plugin) => plugin.publisher === publisher);
            return (
              <li key={publisher}>
                {publisher} <PublisherMark verified={Boolean(card?.publisherVerified)} />
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
