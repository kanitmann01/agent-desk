// The widget card: one bento cell. The vendored GlassSurface carries
// the glass chrome (SVG renderer only, no WebGL path), and the inner
// layout keeps the header and foot contract of the server-rendered
// cards: title, optional pilot badge, freshness stamp, overflow dots,
// body, foot.
//
// Two shells share that content, and they are drawn to look alike at
// rest (same rim, same radius, same shadow, same padding):
//   plain: a steel rim around the glass.
//   tilt:  the vendored TiltedCard tilts the whole card toward the
//          pointer (the commitment card).
// A sparse card (an empty or single-message state) centers its body
// between the header and the foot instead of leaving a void under it.
// Cells rise in on a spring, staggered by the grid; under
// prefers-reduced-motion they render in place.
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { motion, useReducedMotion, type Variants } from 'motion/react';
import GlassSurface from '../vendor/reactbits/GlassSurface';
import TiltedCard from '../vendor/reactbits/TiltedCard';
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

export const CELL_VARIANTS: Variants = {
  hidden: { opacity: 0, y: 26, scale: 0.965 },
  show: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { type: 'spring', stiffness: 130, damping: 17, mass: 0.9 },
  },
};

export const CELL_VARIANTS_STILL: Variants = {
  hidden: { opacity: 1, y: 0, scale: 1 },
  show: { opacity: 1, y: 0, scale: 1 },
};

// Everything around the three measured blocks of a tilt card (header,
// body, foot). Keep in step with .widget in index.css: its padding (16
// top, 12 bottom), the two 14px gaps between the blocks, the glass
// padding (8 on each side) and the 1.5px rim on each side.
const TILT_CHROME = 16 + 12 + 14 + 14 + 16 + 3;

export type CardSpan = 'span-4' | 'span-5' | 'span-7' | 'span-8' | 'span-12';

interface WidgetCardProps {
  title: string;
  span: CardSpan;
  stamp: StampProps;
  badge?: string;
  amber?: boolean;
  shell?: 'plain' | 'tilt';
  // An empty or single-message state: the body is centered vertically.
  sparse?: boolean;
  // Cards that share a row reserve the same number of foot lines, so
  // their foot dividers line up even when one footnote wraps.
  footLines?: 1 | 2;
  foot: ReactNode;
  children: ReactNode;
}

export default function WidgetCard({
  title, span, stamp, badge, amber, shell = 'plain', sparse = false, footLines = 1, foot, children,
}: WidgetCardProps) {
  const reduce = useReducedMotion();
  const headRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const footRef = useRef<HTMLDivElement>(null);
  const [tiltHeight, setTiltHeight] = useState(0);
  const tilt = shell === 'tilt';

  // The vendored TiltedCard positions its face absolutely, so content
  // cannot size it. The cell reserves the content's natural height
  // instead (measured from the three blocks that never stretch), and
  // the tilt fills the cell.
  useLayoutEffect(() => {
    if (!tilt) return undefined;
    const blocks = [headRef.current, bodyRef.current, footRef.current];
    if (blocks.some((block) => block === null)) return undefined;
    const measure = () => setTiltHeight(
      blocks.reduce((sum, block) => sum + (block as HTMLDivElement).offsetHeight, TILT_CHROME),
    );
    measure();
    const observer = new ResizeObserver(measure);
    blocks.forEach((block) => observer.observe(block as HTMLDivElement));
    return () => observer.disconnect();
  }, [tilt]);

  const glass = (
    <div className="card-body">
      <GlassSurface
        borderRadius={22.5}
        backgroundOpacity={0.05}
        refraction={false}
        renderer="svg"
        // The component defaults its width/height PROPS to 200x80 px
        // written as inline styles; explicit 100% strings make the glass
        // fill the bento cell instead.
        width="100%"
        height="100%"
      >
        <article className="widget">
          <div className="w-head" ref={headRef}>
            <h2>{title}</h2>
            {badge ? <span className="badge-pilot">{badge}</span> : null}
            <Stamp {...stamp} />
            {ICON_OPTIONS}
          </div>
          <div className={sparse ? 'w-body sparse' : 'w-body'}>
            <div className="w-body-inner" ref={bodyRef}>{children}</div>
          </div>
          <div className={footLines === 2 ? 'w-foot two-line' : 'w-foot'} ref={footRef}>{foot}</div>
        </article>
      </GlassSurface>
    </div>
  );

  const card = <div className={`card${amber ? ' amber' : ''}`}>{glass}</div>;

  return (
    <motion.div
      className={tilt ? `cell tilt-cell ${span}` : `cell ${span}`}
      variants={reduce ? CELL_VARIANTS_STILL : CELL_VARIANTS}
      style={tilt && tiltHeight ? { minHeight: tiltHeight } : undefined}
    >
      {tilt ? (
        <TiltedCard
          containerWidth="100%"
          containerHeight="100%"
          imageWidth="100%"
          imageHeight="100%"
          radius={24}
          rotateAmplitude={reduce ? 0 : 6}
          scaleOnHover={reduce ? 1 : 1.012}
          glare={reduce ? 0 : 0.28}
          glareColor="#E4EEE9"
          // The cell carries the same resting shadow as a plain card, so
          // the tilt adds none of its own.
          shadow={0}
          parallax={0}
          showTooltip={false}
          flipOnClick={false}
          intro={false}
          gyroscope={false}
          className="tilt-fill"
          style={{ position: 'absolute', inset: 0 }}
        >
          <div className="tilt-content">{card}</div>
        </TiltedCard>
      ) : card}
    </motion.div>
  );
}
