// Publisher list and publisher page. The list is derived from the catalog
// the server already returned (no invented directory), and the page reads
// the publisher proof endpoint.
import { useEffect, useState, type FormEvent } from 'react';
import Button from '../components/Button';
import { useBusy } from '../components/useBusy';
import { getMarket, marketErrorText, postMarket } from './client';
import { MarketLink } from './context';
import { MarketGrid, PublisherMark, SkeletonGrid, SkeletonPanel } from './MarketGrid';
import { formatDate } from './permissions';
import type { CatalogResponse, MarketCard, PublisherResponse } from './types';

interface PublisherSummary {
  name: string;
  verified: boolean;
  plugins: MarketCard[];
}

/**
 * Group catalog cards by publisher, sorted by name.
 *
 * A publisher counts as verified only when every one of its cards is, so a
 * single unverified release is enough to drop the mark.
 */
function groupByPublisher(cards: MarketCard[]): PublisherSummary[] {
  const map = new Map<string, PublisherSummary>();
  for (const card of cards) {
    const current = map.get(card.publisher);
    if (current) {
      current.plugins.push(card);
      current.verified = current.verified && card.publisherVerified;
    } else {
      map.set(card.publisher, {
        name: card.publisher,
        verified: card.publisherVerified,
        plugins: [card],
      });
    }
  }
  return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Render every publisher the catalog knows, with its verification mark and
 * plugin count.
 *
 * The list is derived from the catalog cards rather than a separate
 * directory, so a publisher appears here only while it has a plugin in the
 * catalog.
 */
export function PublishersPage() {
  const [cards, setCards] = useState<MarketCard[] | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const retryBusy = useBusy(retrying);

  useEffect(() => {
    let cancelled = false;
    getMarket<CatalogResponse>('/api/marketplace/catalog')
      .then((data) => {
        if (cancelled) return;
        setCards(data.entries);
        setError('');
        setRetrying(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(marketErrorText(err));
        setRetrying(false);
      });
    return () => { cancelled = true; };
  }, [attempt]);

  if (error) {
    return (
      <div className="mkt-page">
        <h1>Publishers</h1>
        <div className="mkt-error-panel" role="alert">
          <p>{error}</p>
          <Button tone="secondary" disabled={retrying}
                  pending={retryBusy} pendingLabel="Trying again…"
                  onClick={() => { setRetrying(true); setAttempt((n) => n + 1); }}>
            Try again
          </Button>
        </div>
      </div>
    );
  }
  if (!cards) {
    return (
      <div className="mkt-page" aria-busy="true">
        <p className="mkt-result-count">Loading publishers…</p>
        <SkeletonGrid count={3} />
      </div>
    );
  }
  const publishers = groupByPublisher(cards);
  return (
    <div className="mkt-page">
      <header className="mkt-page-head">
        <span className="mkt-eyebrow">Marketplace</span>
        <h1>Publishers</h1>
        <p className="mkt-lede">Every publisher in the catalog, with its verification mark and plugin count.</p>
      </header>
      {publishers.length === 0 ? (
        <p className="mkt-empty-inline">The catalog has no publishers yet.</p>
      ) : (
        <div className="mkt-table-wrap">
          <table className="rows">
            <caption className="mkt-sr-only">Publishers in the marketplace</caption>
            <thead>
              <tr><th scope="col">Publisher</th><th scope="col">Verification</th><th scope="col">Plugins</th><th scope="col">Proof</th></tr>
            </thead>
            <tbody>
              {publishers.map((publisher) => (
                <tr key={publisher.name}>
                  <th scope="row">
                    <MarketLink to={`/marketplace/publisher/${encodeURIComponent(publisher.name)}`}>
                      {publisher.name}
                    </MarketLink>
                  </th>
                  <td><PublisherMark verified={publisher.verified} /></td>
                  <td>{publisher.plugins.length}</td>
                  <td className="w-note">See publisher page</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/**
 * Render a publisher proof as one short phrase.
 *
 * The declared type (or kind, or method) is preferred over the whole record;
 * an object with none of those still reads as a proof on file rather than as
 * a blank, and an absent proof says so.
 */
function proofText(proof: unknown): string {
  if (!proof) return 'No proof on file';
  if (typeof proof === 'string') return proof;
  if (typeof proof === 'object') {
    const record = proof as Record<string, unknown>;
    const type = record.type ?? record.kind ?? record.method;
    if (typeof type === 'string') return type;
    return 'Proof on file';
  }
  return String(proof);
}

/**
 * Render the report form for one publisher, closed until it is asked for.
 *
 * A filed report closes the form and hands its message to the page; a refusal
 * keeps the form open with the server's message so the text is not lost.
 */
function PublisherReport({ name, onDone }: { name: string; onDone: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('Spam or misleading listing');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!open) return <Button tone="secondary" onClick={() => setOpen(true)}>Report this publisher</Button>;
  /**
   * File the report once with the chosen reason and note.
   *
   * On success the form closes and the page is told; on failure the server's
   * message stays beside the fields.
   */
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await postMarket('/api/marketplace/report', { id: `publisher:${name}`, reason, note });
      setBusy(false);
      setOpen(false);
      onDone('Publisher report filed.');
    } catch (err) {
      setBusy(false);
      setError(marketErrorText(err));
    }
  };
  return (
    <form className="mkt-report" onSubmit={submit}>
      <h2>Report {name}</h2>
      <label className="mkt-field">
        <span>Reason</span>
        <select value={reason} onChange={(event) => setReason(event.target.value)}>
          <option>Spam or misleading listing</option>
          <option>Unsafe or deceptive permissions</option>
          <option>Impersonation</option>
          <option>Other</option>
        </select>
      </label>
      <label className="mkt-field">
        <span>Note (optional)</span>
        <textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
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
 * Render one publisher: its proof, whether it is verified, and the plugins it
 * published.
 *
 * The proof endpoint is the only source, so a refusal is shown as "publisher
 * not found" with both a retry and the way back to the list. Filing a report
 * only sets the page's status message; it changes nothing about the
 * publisher.
 */
export function PublisherPage({ name }: { name: string }) {
  const [data, setData] = useState<PublisherResponse | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [message, setMessage] = useState('');

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError('');
    getMarket<PublisherResponse>(`/api/marketplace/publisher/${encodeURIComponent(name)}`)
      .then((payload) => { if (!cancelled) setData(payload); })
      .catch((err) => { if (!cancelled) setError(marketErrorText(err)); });
    return () => { cancelled = true; };
  }, [name, attempt]);

  if (error) {
    return (
      <div className="mkt-page">
        <h1>Publisher not found</h1>
        <div className="mkt-error-panel" role="alert">
          <p>{error}</p>
          <div className="mkt-actions">
            <Button tone="secondary" onClick={() => setAttempt((n) => n + 1)}>Try again</Button>
            <MarketLink className="btn btn-secondary" to="/marketplace/publishers">All publishers</MarketLink>
          </div>
        </div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="mkt-page mkt-skeleton-region" aria-busy="true">
        <p className="mkt-result-count" role="status">Reading the publisher…</p>
        <div className="mkt-page-head">
          <span className="mkt-skel mkt-skel-title" />
          <span className="mkt-skel" />
        </div>
        <SkeletonPanel lines={2} />
        <SkeletonGrid count={3} />
      </div>
    );
  }
  return (
    <div className="mkt-page">
      <nav className="mkt-crumbs" aria-label="Breadcrumb">
        <ol>
          <li><MarketLink to="/marketplace">Marketplace</MarketLink></li>
          <li><MarketLink to="/marketplace/publishers">Publishers</MarketLink></li>
          <li aria-current="page">{data.publisher}</li>
        </ol>
      </nav>
      <header className="mkt-page-head">
        <span className="mkt-eyebrow">Publisher</span>
        <h1>{data.publisher}</h1>
        <p className="mkt-detail-byline">
          <PublisherMark verified={data.verified} />
          <span className="mkt-sep" aria-hidden="true">·</span>
          {data.plugins.length} plugin{data.plugins.length === 1 ? '' : 's'}
          <span className="mkt-sep" aria-hidden="true">·</span>
          First seen {formatDate(data.firstSeen)}
        </p>
      </header>
      {message && <p className="mkt-success" role="status">{message}</p>}
      <section className="mkt-panel" aria-labelledby="mkt-proof">
        <h2 id="mkt-proof">Publisher proof</h2>
        <p>{proofText(data.proof)}</p>
        <p className="w-note">
          Verification says who published this plugin, not that it is safe. The risk tier and permission list still apply.
        </p>
        <PublisherReport name={data.publisher} onDone={setMessage} />
      </section>
      <section className="mkt-panel" aria-labelledby="mkt-pub-plugins">
        <h2 id="mkt-pub-plugins">Plugins by {data.publisher}</h2>
        {data.plugins.length === 0
          ? <p className="mkt-empty-inline">No plugins in the catalog from this publisher.</p>
          : <MarketGrid cards={data.plugins} deskNetwork={data.deskNetwork} />}
      </section>
    </div>
  );
}
