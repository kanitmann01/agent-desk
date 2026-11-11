// The widget card: the vendored GlassSurface carries the glass chrome
// (radius, rim, sheen; SVG renderer only, no WebGL path), and the inner
// layout follows the same header/foot contract as the server-rendered
// cards: title, optional pilot badge, freshness stamp, overflow dots,
// body, foot.
import type { ReactNode } from 'react';
import GlassSurface from '../vendor/reactbits/GlassSurface';
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

interface WidgetCardProps {
  title: string;
  col: 'col-4' | 'col-5' | 'col-7' | 'col-8';
  stamp: StampProps;
  badge?: string;
  amber?: boolean;
  foot: ReactNode;
  children: ReactNode;
}

export default function WidgetCard({ title, col, stamp, badge, amber, foot, children }: WidgetCardProps) {
  return (
    <div className={col}>
      <div className={`widget-shell${amber ? ' amber' : ''}`}>
        <GlassSurface
          borderRadius={12}
          backgroundOpacity={0.8}
          refraction={false}
          renderer="svg"
          // The component defaults its width/height PROPS to 200x80 px
          // written as inline styles; explicit 100% strings make the glass
          // fill the grid column instead.
          width="100%"
          height="100%"
        >
          <article className="widget" style={{ width: '100%' }}>
            <div className="w-head">
              <h2>{title}</h2>
              {badge ? <span className="badge-pilot">{badge}</span> : null}
              <Stamp {...stamp} />
              {ICON_OPTIONS}
            </div>
            {children}
            <div className="w-foot">{foot}</div>
          </article>
        </GlassSurface>
      </div>
    </div>
  );
}
