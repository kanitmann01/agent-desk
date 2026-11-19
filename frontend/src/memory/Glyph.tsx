// One small mark per kind of knowledge point. Shape carries the kind
// (so it reads in every theme and without colour); the theme's --kind-*
// token tints it.
import type { NodeKind } from './types';

export type GlyphKind = NodeKind | 'experience' | 'candidate';

/**
 * The mark for one kind, drawn inside the -6..6 box of a 12px glyph.
 *
 * Shape alone carries the kind so the marks stay apart without colour; the
 * enclosing frame and the theme's tint come from Glyph.
 */
export function GlyphShape({ kind }: { kind: GlyphKind }) {
  switch (kind) {
    case 'origin':
      return <path className="mg-glyph mg-glyph-origin" d="M0 -4.6 4.6 0 0 4.6 -4.6 0Z" />;
    case 'source':
      return <rect className="mg-glyph mg-glyph-source" x={-3.6} y={-4.2} width={7.2} height={8.4} rx={1} />;
    case 'fact':
      return <circle className="mg-glyph mg-glyph-fact" r={4} />;
    case 'experience':
      return (
        <g className="mg-glyph mg-glyph-experience">
          <circle r={3.9} />
          <circle r={1.4} className="mg-glyph-core" />
        </g>
      );
    case 'candidate':
      return <circle className="mg-glyph mg-glyph-candidate" r={3.9} />;
    case 'entity':
      return <rect className="mg-glyph mg-glyph-entity" x={-3.8} y={-3.8} width={7.6} height={7.6} rx={2} />;
    case 'observation':
      return (
        <g className="mg-glyph mg-glyph-observation">
          <circle r={4.4} />
          <circle r={1.8} className="mg-glyph-core" />
        </g>
      );
  }
}

/** A 12px decorative mark for one kind, hidden from assistive technology. */
export function Glyph({ kind }: { kind: GlyphKind }) {
  return (
    <svg className="mg-glyph-box" width="12" height="12" viewBox="-6 -6 12 12" aria-hidden="true">
      <GlyphShape kind={kind} />
    </svg>
  );
}
