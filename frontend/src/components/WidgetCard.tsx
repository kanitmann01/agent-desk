// The widget card: one bento cell. The vendored GlassSurface carries
// the glass chrome (SVG renderer only, no WebGL path), and the inner
// layout keeps the header and foot contract of the server-rendered
// cards: title, optional pilot badge, freshness stamp, overflow dots,
// body, foot.
//
// Three shells share that content:
//   plain: a steel rim around the glass.
//   star:  the vendored StarBorder runs a light around the rim (the
//          hero sales card).
//   tilt:  the vendored TiltedCard tilts the whole card toward the
//          pointer (the commitment card).
// Cells rise in on a spring, staggered by the grid; under
// prefers-reduced-motion they render in place.
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { motion, useReducedMotion, type Variants } from 'motion/react';
import GlassSurface from '../vendor/reactbits/GlassSurface';
import StarBorder from '../vendor/reactbits/StarBorder';
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

// Everything around the measured content of a tilt card: the widget's
// own padding (14 top, 10 bottom) and gap (12), the glass padding (8 on
// each side) and the 1.5px rim on each side.
const TILT_CHROME = 14 + 10 + 12 + 16 + 3;

export type CardSpan = 'span-4' | 'span-5' | 'span-7' | 'span-8' | 'span-12';

interface WidgetCardProps {
  title: string;
  span: CardSpan;
  stamp: StampProps;
  badge?: string;
  amber?: boolean;
  shell?: 'plain' | 'star' | 'tilt';
  foot: ReactNode;
  children: ReactNode;
}

export default function WidgetCard({ title, span, stamp, badge, amber, shell = 'plain', foot, children }: WidgetCardProps) {
  const reduce = useReducedMotion();
  const mainRef = useRef<HTMLDivElement>(null);
  const footRef = useRef<HTMLDivElement>(null);
  const [tiltHeight, setTiltHeight] = useState(0);
  const tilt = shell === 'tilt';

  // The vendored TiltedCard positions its face absolutely, so content
  // cannot size it. The cell reserves the content's natural height
  // instead (measured from the two blocks that never stretch), and the
  // tilt fills the cell.
  useLayoutEffect(() => {
    if (!tilt) return undefined;
    const main = mainRef.current;
    const footer = footRef.current;
    if (!main || !footer) return undefined;
    const measure = () => setTiltHeight(main.offsetHeight + footer.offsetHeight + TILT_CHROME);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(main);
    observer.observe(footer);
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
          <div className="w-main" ref={mainRef}>
            <div className="w-head">
              <h2>{title}</h2>
              {badge ? <span className="badge-pilot">{badge}</span> : null}
              <Stamp {...stamp} />
              {ICON_OPTIONS}
            </div>
            {children}
          </div>
          <div className="w-foot" ref={footRef}>{foot}</div>
        </article>
      </GlassSurface>
    </div>
  );

  let body;
  if (shell === 'star') {
    body = (
      <div className={`card star${amber ? ' amber' : ''}`}>
        <StarBorder
          as="div"
          color={amber ? '#F59E0B' : '#22C55E'}
          trailColor={amber ? '#FCD34D' : '#22D3EE'}
          radius={24}
          thickness={1.5}
          duration={7}
          trailLength={0.4}
          stars={2}
          glow={0.8}
          hover="brighten"
          clickPulse={false}
          backgroundColor="transparent"
          textColor="inherit"
          borderColor={amber ? 'rgba(245,158,11,.5)' : 'rgba(71,85,105,.8)'}
          style={{
            display: 'flex',
            flex: 1,
            minWidth: 0,
            padding: '1.5px',
            gap: 0,
            alignItems: 'stretch',
            justifyContent: 'flex-start',
            fontWeight: 'inherit',
            lineHeight: 'inherit',
          }}
        >
          {glass}
        </StarBorder>
      </div>
    );
  } else if (tilt) {
    body = (
      <TiltedCard
        containerWidth="100%"
        containerHeight="100%"
        imageWidth="100%"
        imageHeight="100%"
        radius={24}
        rotateAmplitude={reduce ? 0 : 6}
        scaleOnHover={reduce ? 1 : 1.012}
        glare={reduce ? 0 : 0.38}
        glareColor="#7DD3FC"
        shadow={0.5}
        parallax={0}
        showTooltip={false}
        flipOnClick={false}
        intro={false}
        gyroscope={false}
        className="tilt-fill"
        style={{ position: 'absolute', inset: 0 }}
      >
        <div className="tilt-content">
          <div className={`card${amber ? ' amber' : ''}`}>{glass}</div>
        </div>
      </TiltedCard>
    );
  } else {
    body = <div className={`card${amber ? ' amber' : ''}`}>{glass}</div>;
  }

  return (
    <motion.div
      className={`cell ${span}`}
      variants={reduce ? CELL_VARIANTS_STILL : CELL_VARIANTS}
      style={tilt && tiltHeight ? { minHeight: tiltHeight } : undefined}
    >
      {body}
    </motion.div>
  );
}
