// The widget card: one bento cell. A Card White article on the paper,
// the paper-lift shadow the only depth, carrying the header contract of
// the server-rendered cards: title, optional pilot badge, freshness
// stamp, overflow dots, body, foot.
//
// A sparse card (an empty or single-message state) centers its body
// between the header and the foot instead of leaving a void under it.
import type { ReactNode } from 'react';
import Stamp, { type StampProps } from './Stamp';

const ICON_OPTIONS = (
  <button className="icon-btn" type="button" aria-label="Widget options">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="5" cy="12" r="1.7" />
      <circle cx="12" cy="12" r="1.7" />
      <circle cx="19" cy="12" r="1.7" />
    </svg>
  </button>
);

export type CardSpan = 'span-4' | 'span-5' | 'span-7' | 'span-8' | 'span-12';

interface WidgetCardProps {
  title: string;
  span: CardSpan;
  stamp: StampProps;
  badge?: string;
  // Stale and blocked states keep the card paper-white; the amber pair
  // lives on the stamp and the alert block, never on the card chrome.
  amber?: boolean;
  // An empty or single-message state: the body is centered vertically.
  sparse?: boolean;
  // Cards that share a row reserve the same number of foot lines, so
  // their foot dividers line up even when one footnote wraps.
  footLines?: 1 | 2;
  foot: ReactNode;
  children: ReactNode;
}

export default function WidgetCard({
  title, span, stamp, badge, amber, sparse = false, footLines = 1, foot, children,
}: WidgetCardProps) {
  return (
    <div className={`cell ${span}`}>
      <div className={`card${amber ? ' amber' : ''}`}>
        <article className="widget">
          <div className="w-head">
            <h2>{title}</h2>
            {badge ? <span className="badge-pilot">{badge}</span> : null}
            <Stamp {...stamp} />
            {ICON_OPTIONS}
          </div>
          <div className={sparse ? 'w-body sparse' : 'w-body'}>
            <div className="w-body-inner">{children}</div>
          </div>
          <div className={footLines === 2 ? 'w-foot two-line' : 'w-foot'}>{foot}</div>
        </article>
      </div>
    </div>
  );
}
