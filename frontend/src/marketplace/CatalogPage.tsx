// Discover, Search and Category are one surface with one grid. The URL
// holds the question; local controls hold the filters, and every request
// goes through the server's catalog so counts are never invented.
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import EmptyState, { ICON_SEARCH } from '../components/EmptyState';
import Button from '../components/Button';
import { getMarket, marketErrorText } from './client';
import { useMarketplaceNav } from './context';
import { MarketCatalog, SkeletonGrid, CATEGORIES, categoryLabel } from './MarketGrid';
import type { CatalogResponse } from './types';

type Load =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: CatalogResponse; offline?: string };

const SOURCES = ['bundled', 'org', 'peer', 'installed'];
const RISKS = ['low', 'medium', 'high'];
const CATALOG_CACHE_KEY = 'agentdesk.marketplace.catalog.v1';

interface CachedCatalog {
  savedAt: string;
  data: CatalogResponse;
}

function readCatalogCache(): CachedCatalog | null {
  try {
    const raw = window.localStorage.getItem(CATALOG_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<CachedCatalog>;
    if (!parsed || typeof parsed.savedAt !== 'string' || !parsed.data
        || !Array.isArray(parsed.data.entries)) return null;
    return { savedAt: parsed.savedAt, data: parsed.data as CatalogResponse };
  } catch {
    return null;
  }
}

function saveCatalogCache(data: CatalogResponse): void {
  try {
    window.localStorage.setItem(CATALOG_CACHE_KEY, JSON.stringify({
      savedAt: new Date().toISOString(), data,
    }));
  } catch {
    // A browser with storage disabled still gets the live catalog.
  }
}

function savedLabel(savedAt: string): string {
  const date = new Date(savedAt);
  return Number.isNaN(date.getTime()) ? 'at an unknown time' : `on ${date.toLocaleString()}`;
}

export function CatalogPage({ route }: { route: { name: string; params: Record<string, string> } }) {
  const { navigate } = useMarketplaceNav();
  const onSearch = route.name === 'search';
  const category = route.name === 'category' ? route.params.category : '';
  const committedQ = onSearch ? route.params.q : '';
  const [q, setQ] = useState(committedQ);
  const [source, setSource] = useState('');
  const [risk, setRisk] = useState('');
  const [eligibleOnly, setEligibleOnly] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [load, setLoad] = useState<Load>({ kind: 'loading' });

  useEffect(() => { setQ(committedQ); }, [committedQ]);

  useEffect(() => {
    const controller = { cancelled: false };
    setLoad({ kind: 'loading' });
    const params = new URLSearchParams();
    if (committedQ) params.set('q', committedQ);
    if (category) params.set('category', category);
    if (source) params.set('source', source);
    if (risk) params.set('risk', risk);
    if (eligibleOnly) params.set('eligible', '1');
    const query = params.toString();
    getMarket<CatalogResponse>(`/api/marketplace/catalog${query ? `?${query}` : ''}`)
      .then((data) => {
        if (controller.cancelled) return;
        setLoad({ kind: 'ready', data });
        if (!committedQ && !category && !source && !risk && !eligibleOnly) {
          saveCatalogCache(data);
        }
      })
      .catch((err) => {
        if (controller.cancelled) return;
        const cached = !committedQ && !category && !source && !risk && !eligibleOnly
          ? readCatalogCache()
          : null;
        if (cached) {
          setLoad({ kind: 'ready', data: cached.data, offline: cached.savedAt });
        } else {
          setLoad({ kind: 'error', message: marketErrorText(err) });
        }
      });
    return () => { controller.cancelled = true; };
  }, [committedQ, category, source, risk, eligibleOnly, attempt]);

  const submit = useCallback((event: FormEvent) => {
    event.preventDefault();
    const trimmed = q.trim();
    navigate(trimmed ? `/marketplace/search?q=${encodeURIComponent(trimmed)}` : '/marketplace');
  }, [q, navigate]);

  const clearFilters = () => {
    setSource('');
    setRisk('');
    setEligibleOnly(false);
    if (category || committedQ) { setQ(''); navigate('/marketplace'); }
  };

  const heading = category
    ? `${categoryLabel(category)} plugins`
    : onSearch ? 'Search results' : 'Discover plugins';
  const lede = category
    ? `Plugins in the ${categoryLabel(category).toLowerCase()} category, with publisher and risk on every card.`
    : onSearch
      ? 'Results match names, summaries, tags, publishers and the words in a plugin\'s summary.'
      : 'Install work plugins that read only what they declare. Every card shows the publisher, risk tier and source.';

  return (
    <div className="mkt-page">
      <header className="mkt-page-head">
        <h1>{heading}</h1>
        <p className="mkt-lede">
          {category || onSearch
            ? lede
            : 'Install work plugins that read only what they declare.'}
        </p>
      </header>

      <div className="mkt-toolbar">
      <form className="mkt-search" role="search" onSubmit={submit}>
        <label className="mkt-sr-only" htmlFor="mkt-q">Search plugins</label>
        <div className="mkt-search-field">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            id="mkt-q"
            type="search"
            value={q}
            placeholder="Search by name, job, or tag"
            onChange={(event) => setQ(event.target.value)}
            autoComplete="off"
          />
        </div>
        <Button tone="primary" type="submit">Search</Button>
      </form>

      <div className="mkt-filters">
        <div className="mkt-filter-group" role="group" aria-label="Category">
          <span className="mkt-filter-label">Category</span>
          <div className="mkt-chip-row">
            <button type="button" className="mkt-filter-chip"
                    aria-pressed={category === ''}
                    onClick={() => navigate(onSearch && committedQ ? `/marketplace/search?q=${encodeURIComponent(committedQ)}` : '/marketplace')}>
              All
            </button>
            {CATEGORIES.map((slug) => (
              <button
                key={slug}
                type="button"
                className="mkt-filter-chip"
                aria-pressed={category === slug}
                onClick={() => navigate(`/marketplace/category/${slug}`)}
              >
                {categoryLabel(slug)}
              </button>
            ))}
          </div>
        </div>
        <div className="mkt-filter-row">
          <label className="mkt-select">
            <span>Source</span>
            <select value={source} onChange={(event) => setSource(event.target.value)}>
              <option value="">Any source</option>
              {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="mkt-select">
            <span>Risk</span>
            <select value={risk} onChange={(event) => setRisk(event.target.value)}>
              <option value="">Any risk</option>
              {RISKS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label className="mkt-toggle">
            <input type="checkbox" checked={eligibleOnly}
                   onChange={(event) => setEligibleOnly(event.target.checked)} />
            <span>Only available plugins</span>
          </label>
        </div>
      </div>
      </div>

      {load.kind === 'loading' && (
        <div className="mkt-results" aria-busy="true" aria-live="polite">
          <p className="mkt-result-count">Loading plugins…</p>
          <SkeletonGrid />
        </div>
      )}

      {load.kind === 'error' && (
        <div className="mkt-error-panel" role="alert">
          <h2>The catalog did not load</h2>
          <p>{load.message}</p>
          <p className="w-note">
            {(committedQ || category || source || risk || eligibleOnly)
              ? 'No saved catalog for these filters is available offline.'
              : 'No saved catalog is available offline yet.'}
          </p>
          <Button tone="secondary" onClick={() => setAttempt((n) => n + 1)}>Try again</Button>
        </div>
      )}

      {load.kind === 'ready' && (
        <div className="mkt-results">
          {load.offline && (
            <div className="mkt-offline" role="status">
              <strong>Offline</strong>
              <span>Showing the last saved catalog, {savedLabel(load.offline)}. Nothing was invented.</span>
              <Button tone="secondary" onClick={() => setAttempt((n) => n + 1)}>Retry</Button>
            </div>
          )}
          <p className="mkt-result-count" aria-live="polite">
            {load.data.total === 0
              ? 'No plugins'
              : `${load.data.entries.length} of ${load.data.total} plugin${load.data.total === 1 ? '' : 's'}`}
            {category && ` in ${categoryLabel(category)}`}
            {committedQ && ` matching “${committedQ}”`}
          </p>
          {load.data.entries.length === 0 ? (
            <EmptyState
              icon={ICON_SEARCH}
              action={<Button tone="secondary" onClick={clearFilters}>Clear filters</Button>}
            >
              <span>No plugins match those filters.</span>
              <span className="w-note mkt-empty-line">Try a category, a shorter search, or allow every source.</span>
            </EmptyState>
          ) : (
            <MarketCatalog cards={load.data.entries} />
          )}
        </div>
      )}
    </div>
  );
}
