// The one plugin grid Discover, Search, Category and Publisher share.
// Cards are links (keyboard accessible by default) with every status
// carried by text as well as colour.
import type { MarketCard } from './types';
import { MarketLink } from './context';
import { PluginIcon } from './icons';

export const CATEGORIES = [
  'finance', 'time', 'communication', 'research',
  'operations', 'command', 'reference',
] as const;

const SOURCE_LABELS: Record<string, string> = {
  bundled: 'Bundled',
  org: 'Organization',
  peer: 'Peer',
  installed: 'Installed',
};

const RISK_LABELS: Record<string, string> = {
  internal: 'Internal risk',
  low: 'Low risk',
  medium: 'Medium risk',
  high: 'High risk',
};

export function categoryLabel(category: string): string {
  return category.charAt(0).toUpperCase() + category.slice(1);
}

export function riskLabel(tier: string): string {
  return RISK_LABELS[tier] ?? `${tier} risk`;
}

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

export function PublisherMark({ verified }: { verified: boolean }) {
  return verified ? (
    <span className="mkt-verified" title="Publisher verified">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
        <path d="m4 12 5 5L20 6" />
      </svg>
      <span>Verified</span>
    </span>
  ) : (
    <span className="mkt-unverified">Unverified publisher</span>
  );
}

export function MarketGrid({ cards }: { cards: MarketCard[] }) {
  return (
    <ul className="mkt-grid" role="list">
      {cards.map((card) => <li key={card.id}><MarketCardView card={card} /></li>)}
    </ul>
  );
}

export function MarketCardView({ card }: { card: MarketCard }) {
  const reason = card.ineligibleReasons[0];
  return (
    <MarketLink
      to={`/marketplace/plugin/${encodeURIComponent(card.id)}`}
      className={`mkt-card${card.eligible ? '' : ' mkt-card-blocked'}`}
      aria-label={`${card.name}, version ${card.version}, ${card.publisher}. View plugin details`}
    >
      <div className="mkt-card-top">
        <span className="mkt-card-icon"><PluginIcon name={card.icon} /></span>
        <div className="mkt-card-id">
          <span className="mkt-card-name">{card.name}</span>
          <span className="mkt-card-pub">
            {card.publisher}
            <PublisherMark verified={card.publisherVerified} />
          </span>
        </div>
        <span className="mkt-version">v{card.version}</span>
      </div>
      <p className="mkt-card-summary">{card.summary}</p>
      <div className="mkt-card-tags">
        <span className="mkt-tag">{categoryLabel(card.category)}</span>
        <span className={`mkt-risk mkt-risk-${card.riskTier}`}>
          <span className="mkt-dot" aria-hidden="true" />
          {riskLabel(card.riskTier)}
        </span>
        <span className="mkt-source">{sourceLabel(card.source)}</span>
        {card.sampleAvailable && <span className="mkt-chip">Sample</span>}
        {card.deprecated && <span className="mkt-chip mkt-chip-warn">Deprecated</span>}
        {card.yanked && <span className="mkt-chip mkt-chip-warn">Yanked</span>}
      </div>
      {!card.eligible && reason && (
        <p className="mkt-ineligible">
          <span className="mkt-ineligible-label">Not available:</span> {reason.message}
        </p>
      )}
    </MarketLink>
  );
}

const QUIET_RISK = new Set(['low', 'internal', 't1']);

function isHouseDefault(card: MarketCard): boolean {
  return card.publisher === 'agent-desk'
    && card.publisherVerified
    && card.source === 'bundled'
    && QUIET_RISK.has(card.riskTier.toLowerCase());
}

// What a featured plugin draws on the desk, in miniature. Shapes, not
// numbers: the catalog previews the cell, it does not report data.
function Miniature({ id }: { id: string }) {
  const base = id.split('~')[0];
  if (base === 'ar-aging' || base === 'renewal-radar') {
    const buckets: Array<[string, number]> = [['0–30', 92], ['31–60', 58], ['61–90', 30], ['90+', 16]];
    return (
      <div className="mini mini-aging" aria-hidden="true">
        {buckets.map(([label, h]) => (
          <span key={label} className="mini-col"><span className="mini-bar" style={{ height: `${h}%` }} /><span className="mini-x">{label}</span></span>
        ))}
      </div>
    );
  }
  if (base === 'budget-burn' || base === 'revenue-vs-target' || base === 'kpi-scorecard' || base === 'excel-report') {
    return (
      <div className="mini mini-pace" aria-hidden="true">
        <div className="mini-pace-row"><span className="mini-pace-fig">68%</span><span className="mini-x">of month spent · day 17 of 30</span></div>
        <div className="mini-pace-track"><span style={{ width: '68%' }} /><i style={{ left: '57%' }} /></div>
      </div>
    );
  }
  if (base === 'competitor-watch' || base === 'source-ledger' || base === 'reconciliation-watch') {
    return (
      <div className="mini mini-diff" aria-hidden="true">
        <span className="del">− old line</span>
        <span className="ins">+ new line</span>
      </div>
    );
  }
  return (
    <ol className="mini mini-events" aria-hidden="true">
      <li><span className="mini-t">09:12</span><span className="mini-line" style={{ width: '70%' }} /></li>
      <li><span className="mini-t">11:40</span><span className="mini-line" style={{ width: '52%' }} /></li>
      <li><span className="mini-t">14:05</span><span className="mini-line" style={{ width: '84%' }} /></li>
    </ol>
  );
}

function Row({ card, featured = false }: { card: MarketCard; featured?: boolean }) {
  const showMeta = !isHouseDefault(card);
  const extras: string[] = [];
  if (showMeta && card.publisher !== 'agent-desk') extras.push(card.publisher);
  if (showMeta && !card.publisherVerified) extras.push('Unverified publisher');
  if (showMeta && card.source !== 'bundled') extras.push(sourceLabel(card.source));
  if (card.deprecated) extras.push('Deprecated');
  if (card.yanked) extras.push('Yanked');
  const reason = card.ineligibleReasons[0];
  return (
    <li>
      <MarketLink
        to={`/marketplace/plugin/${encodeURIComponent(card.id)}`}
        className={`mkt-row${featured ? ' mkt-row-featured' : ''}${card.eligible ? '' : ' mkt-card-blocked'}`}
        aria-label={`${card.name}, version ${card.version}, ${card.publisher}. View plugin details`}
      >
        {featured ? <Miniature id={card.id} /> : null}
        <span className="mkt-row-name">{card.name}</span>
        <span className="mkt-row-summary">{card.summary}</span>
        {featured ? (
          <span className="mkt-row-cat">{categoryLabel(card.category)} <span className="mkt-version">v{card.version}</span></span>
        ) : <span className="mkt-version">v{card.version}</span>}
        {showMeta && !QUIET_RISK.has(card.riskTier.toLowerCase())
          ? <span className="mkt-row-extra">{riskLabel(card.riskTier)}</span> : null}
        {extras.map((extra) => <span key={extra} className="mkt-row-extra">{extra}</span>)}
        {!card.eligible && reason ? (
          <p className="mkt-ineligible"><span className="mkt-ineligible-label">Not available:</span> {reason.message}</p>
        ) : null}
      </MarketLink>
    </li>
  );
}

/** Discover list: a few featured rows, then one section per category. */
export function MarketCatalog({ cards }: { cards: MarketCard[] }) {
  const featured = cards.filter((card) => card.eligible).slice(0, 3);
  const featuredIds = new Set(featured.map((card) => card.id));
  const rest = cards.filter((card) => !featuredIds.has(card.id));
  const house = cards.length > 0 && cards.every(isHouseDefault);
  const groups = new Map<string, MarketCard[]>();
  for (const card of rest) {
    const list = groups.get(card.category) ?? [];
    list.push(card);
    groups.set(card.category, list);
  }
  return (
    <div className="mkt-catalog">
      {house ? null : (
        <p className="mkt-default-note">Publisher, verification and risk show only when a plugin is not the bundled default.</p>
      )}
      {featured.length > 0 ? (
        <section className="mkt-group" aria-label="Featured">
          <h2>Featured</h2>
          <ul className="mkt-rows mkt-featured">
            {featured.map((card) => <Row key={card.id} card={card} featured />)}
          </ul>
        </section>
      ) : null}
      {[...groups.entries()].map(([category, group]) => (
        <section key={category} className="mkt-group" aria-label={categoryLabel(category)}>
          <h2>{categoryLabel(category)}</h2>
          <ul className="mkt-rows">
            {group.map((card) => <Row key={card.id} card={card} />)}
          </ul>
        </section>
      ))}
    </div>
  );
}

export function SkeletonGrid({ count = 6 }: { count?: number }) {
  return (
    <div className="mkt-grid mkt-grid-skeleton" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div className="mkt-skel-card" key={i}>
          <span className="mkt-skel mkt-skel-title" />
          <span className="mkt-skel" />
          <span className="mkt-skel" />
          <span className="mkt-skel mkt-skel-short" />
        </div>
      ))}
    </div>
  );
}
