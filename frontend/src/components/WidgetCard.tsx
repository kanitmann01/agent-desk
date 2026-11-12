// The widget card: one bento cell. A Card White article on the paper,
// the paper-lift shadow the only depth, carrying the header contract of
// the server-rendered cards: title, optional pilot badge, freshness
// stamp, overflow dots, body, foot.
//
// A sparse card (an empty or single-message state) centers its body
// between the header and the foot instead of leaving a void under it.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import Stamp, { type StampProps } from './Stamp';

export type CardSpan = 'span-4' | 'span-5' | 'span-7' | 'span-8' | 'span-12';

// One action in the card's overflow menu. Either an action callback
// (fires once, menu closes) or an href (a link rendered as the item;
// following it is the action). A disabled item stays visible but
// refuses clicks, so an in-flight action cannot be re-fired.
export interface CardMenuItem {
  label: string;
  onSelect?: () => void;
  href?: string;
  disabled?: boolean;
}

const ICON_DOTS = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <circle cx="5" cy="12" r="1.7" />
    <circle cx="12" cy="12" r="1.7" />
    <circle cx="19" cy="12" r="1.7" />
  </svg>
);

// The header contract's overflow menu: a trigger that announces itself,
// a menu of real items, Escape and outside-click to leave, and the
// focus handed back to the trigger on the way out.
function CardMenu({ items }: { items: CardMenuItem[] }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    function onPointerDown(event: PointerEvent) {
      if (wrapRef.current && event.target instanceof Node && wrapRef.current.contains(event.target)) {
        return;
      }
      setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <div className="w-menu-wrap" ref={wrapRef}>
      <button
        ref={triggerRef}
        className="icon-btn"
        type="button"
        aria-label="Widget options"
        aria-haspopup="menu"
        aria-expanded={open ? 'true' : 'false'}
        onClick={() => setOpen((value) => !value)}
      >
        {ICON_DOTS}
      </button>
      {open ? (
        <div className="w-menu" role="menu" aria-label="Widget options">
          {items.map((item) => (
            item.href !== undefined ? (
              <a
                key={item.label}
                className="w-menuitem"
                role="menuitem"
                href={item.href}
                onClick={() => {
                  setOpen(false);
                  triggerRef.current?.focus();
                }}
              >
                {item.label}
              </a>
            ) : (
              <button
                key={item.label}
                className="w-menuitem"
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  setOpen(false);
                  triggerRef.current?.focus();
                  item.onSelect?.();
                }}
              >
                {item.label}
              </button>
            )
          ))}
        </div>
      ) : null}
    </div>
  );
}

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
  // The header contract's overflow menu. A card that declares no items
  // carries no dots: an empty menu would be a dead control.
  menuItems?: CardMenuItem[];
  foot: ReactNode;
  children: ReactNode;
}

export default function WidgetCard({
  title, span, stamp, badge, amber, sparse = false, footLines = 1, menuItems, foot, children,
}: WidgetCardProps) {
  return (
    <div className={`cell ${span}`}>
      <div className={`card${amber ? ' amber' : ''}`}>
        <article className="widget">
          <div className="w-head">
            <h2>{title}</h2>
            {badge ? <span className="badge-pilot">{badge}</span> : null}
            <Stamp {...stamp} />
            {menuItems && menuItems.length > 0 ? <CardMenu items={menuItems} /> : null}
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
