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
