// The one plugin grid Discover, Search, Category and Publisher share.
// Cards are links (keyboard accessible by default) with every status
// carried by text as well as colour.
import type { MarketCard } from './types';
import { MarketLink } from './context';
import { PluginIcon } from './icons';
import { asksForWeb } from './permissions';

const CANNOT_RUN = 'Cannot run on this desk';

/**
 * True when the card's own capability data asks for web access the desk
 * does not have.
 *
 * Both facts are required: an absent transport field or an absent
 * capability block claims nothing.
 */
function cannotRunHere(card: MarketCard, deskNetwork: boolean | undefined): boolean {
  return deskNetwork === false && asksForWeb(card.capabilities);
}

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

/** Capitalise a category slug for display, leaving the rest of it alone. */
export function categoryLabel(category: string): string {
  return category.charAt(0).toUpperCase() + category.slice(1);
}

/** Name a risk tier for a person, falling back to "<tier> risk" for one this build does not know. */
export function riskLabel(tier: string): string {
  return RISK_LABELS[tier] ?? `${tier} risk`;
}

/** Name a card's source, falling back to the raw value for an unknown one. */
export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

/**
 * Show whether a publisher is verified, in words as well as with a check mark.
 *
 * Unverified is stated outright rather than left blank, so the absence of a
 * mark cannot be mistaken for a pass.
 */
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

/** Render the shared plugin grid as a list of cards, each linking to its detail page. */
export function MarketGrid({ cards, deskNetwork }: { cards: MarketCard[]; deskNetwork?: boolean }) {
  return (
    <ul className="mkt-grid" role="list">
      {cards.map((card) => (
        <li key={card.id}><MarketCardView card={card} deskNetwork={deskNetwork} /></li>
      ))}
    </ul>
  );
}

/**
 * Render one catalog card: identity, summary, category, risk and source, with
 * the deprecation and yank flags when they apply.
 *
 * A blocked plugin keeps its link but carries the first ineligibility reason,
 * so a person can read why before opening it.
 */
export function MarketCardView({ card, deskNetwork }: { card: MarketCard; deskNetwork?: boolean }) {
  const reason = card.ineligibleReasons[0];
  const cannotRun = cannotRunHere(card, deskNetwork);
  return (
    <MarketLink
      to={`/marketplace/plugin/${encodeURIComponent(card.id)}`}
      className={`mkt-card${card.eligible ? '' : ' mkt-card-blocked'}`}
      aria-label={`${card.name}, version ${card.version}, ${card.publisher}, ${categoryLabel(card.category)}${cannotRun ? '. Cannot run on this desk' : ''}. View plugin details`}
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
      <p className="mkt-card-summary" title={card.summary}>{card.summary}</p>
      <div className="mkt-card-tags">
        <span className="mkt-tag" tabIndex={0} title={categoryLabel(card.category)}>{categoryLabel(card.category)}</span>
        <span className={`mkt-risk mkt-risk-${card.riskTier}`}>
          <span className="mkt-dot" aria-hidden="true" />
          {riskLabel(card.riskTier)}
        </span>
        <span className="mkt-source">{sourceLabel(card.source)}</span>
        {cannotRun && <span className="mkt-chip">{CANNOT_RUN}</span>}
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

/**
 * True when a card is this desk's own bundled, verified plugin at a quiet risk
 * tier.
 *
 * The grid treats those as the default and stops annotating them, so a page
 * full of house plugins reads as one product rather than as a list of
 * exceptions.
 */
function isHouseDefault(card: MarketCard): boolean {
  return card.publisher === 'agent-desk'
    && card.publisherVerified
    && card.source === 'bundled'
    && QUIET_RISK.has(card.riskTier.toLowerCase());
}

// What a shipped plugin draws on the desk, in miniature. Shapes, not
// numbers: the catalog previews the cell, it does not report data.
/**
 * Draw the decorative miniature that stands in for a featured plugin's widget.
 *
 * The shape is chosen from the plugin's base id, with any variant suffix
 * dropped, and reports no data: it is hidden from assistive technology
 * because it is illustration, not evidence.
 */
function Miniature({ id }: { id: string }) {
  const base = id.split('~')[0];
  if (base === 'excel-report') {
    return (
      <div className="mini mini-pace" aria-hidden="true">
        <div className="mini-pace-row"><span className="mini-pace-fig">68%</span><span className="mini-x">of month spent · day 17 of 30</span></div>
        <div className="mini-pace-track"><span style={{ width: '68%' }} /><i style={{ left: '57%' }} /></div>
      </div>
    );
  }
  if (base === 'competitor-watch') {
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

/**
 * Render one catalog row.
 *
 * A house-default plugin is shown without the publisher, verification and
 * source tags the default implies; everything else adds them. `featured` also
 * prepends the miniature and promotes the row.
 */
function Row({ card, featured = false, deskNetwork }: {
  card: MarketCard; featured?: boolean; deskNetwork?: boolean;
}) {
  const showMeta = !isHouseDefault(card);
  const cannotRun = cannotRunHere(card, deskNetwork);
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
        aria-label={`${card.name}, version ${card.version}, ${card.publisher}, ${categoryLabel(card.category)}${cannotRun ? '. Cannot run on this desk' : ''}. View plugin details`}
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
        {cannotRun && <span className="mkt-chip">{CANNOT_RUN}</span>}
        {!card.eligible && reason ? (
          <p className="mkt-ineligible"><span className="mkt-ineligible-label">Not available:</span> {reason.message}</p>
        ) : null}
      </MarketLink>
    </li>
  );
}

/** Discover list: a few featured rows, then one section per category. */
export function MarketCatalog({ cards, deskNetwork }: { cards: MarketCard[]; deskNetwork?: boolean }) {
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
            {featured.map((card) => <Row key={card.id} card={card} featured deskNetwork={deskNetwork} />)}
          </ul>
        </section>
      ) : null}
      {[...groups.entries()].map(([category, group]) => (
        <section key={category} className="mkt-group" aria-label={categoryLabel(category)}>
          <h2>{categoryLabel(category)}</h2>
          <ul className="mkt-rows">
            {group.map((card) => <Row key={card.id} card={card} deskNetwork={deskNetwork} />)}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** Render placeholder cards for a grid that is still loading, hidden from assistive technology. */
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

/**
 * Render one panel-shaped placeholder: a heading line and body lines.
 *
 * It borrows the panel's own box and rhythm, so the region that receives the
 * result keeps its shape while the result is read. Hidden from assistive
 * technology; the phase line beside it carries the words.
 */
export function SkeletonPanel({ lines = 3 }: { lines?: number }) {
  return (
    <div className="mkt-panel mkt-panel-skel" aria-hidden="true">
      <span className="mkt-skel mkt-skel-title" />
      {Array.from({ length: lines }, (_, i) => <span className="mkt-skel" key={i} />)}
    </div>
  );
}
