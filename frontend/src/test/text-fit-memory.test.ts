// @vitest-environment node
// Text fit in the two memory islands: the rules that keep prose wrapping,
// rows and chips inside their tiles, fixed labels in their tracks and
// deliberate scrollers scrolling. These tests read the stylesheets; the
// matching markup (the title attributes that make an ellipsis reachable)
// is asserted in memory-graph.test.tsx.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const graphCss = readFileSync(resolve(here, '..', 'memory', 'memory-graph.css'), 'utf8');
const loopCss = readFileSync(resolve(here, '..', 'memory', 'loop', 'memory-loop.css'), 'utf8');

/** The declarations inside the first rule with this exact selector. */
function rule(css: string, selector: string): string {
  const start = css.indexOf(`${selector}{`);
  expect(start, `missing rule ${selector}`).toBeGreaterThanOrEqual(0);
  const end = css.indexOf('}', start);
  return css.slice(start + selector.length + 1, end);
}

/** The body of the first media query with this exact header. */
function media(css: string, header: string): string {
  const start = css.indexOf(`${header}{`);
  expect(start, `missing media query ${header}`).toBeGreaterThanOrEqual(0);
  let depth = 0;
  for (let i = start + header.length; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    else if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(start + header.length + 1, i);
    }
  }
  throw new Error(`unclosed media query ${header}`);
}

describe('memory graph text fit', () => {
  it('breaks prose anywhere on the graph root', () => {
    expect(rule(graphCss, '#memory-graph-root .mg')).toContain('overflow-wrap:anywhere');
  });

  it('wraps the graph header before squeezing its link', () => {
    expect(rule(graphCss, '#memory-graph-root .mg-head')).toContain('flex-wrap:wrap');
    const copy = rule(graphCss, '#memory-graph-root .mg-head>div');
    expect(copy).toContain('flex:1 1 220px');
    expect(copy).toContain('min-width:0');
    expect(rule(graphCss, '#memory-graph-root .mg-open')).toContain('flex:none');
  });

  it('keeps a pipeline step label inside its cell', () => {
    expect(rule(graphCss, '#memory-graph-root .mg-step-top')).toContain('flex-wrap:wrap');
    const name = rule(graphCss, '#memory-graph-root .mg-step-name');
    expect(name).toContain('min-width:0');
    expect(name).toContain('white-space:nowrap');
    expect(name).toContain('text-overflow:ellipsis');
    const count = rule(graphCss, '#memory-graph-root .mg-step-count');
    expect(count).toContain('white-space:nowrap');
    expect(count).toContain('overflow-x:auto');
    expect(rule(graphCss, '#memory-graph-root .mg-step-count:focus-visible')).toContain('outline:2px solid var(--focus)');
  });

  it('clips the picture column titles to their own column', () => {
    const title = rule(graphCss, '#memory-graph-root .mg-cols .mg-col-title');
    expect(title).toContain('overflow:hidden');
    expect(title).toContain('text-overflow:ellipsis');
    expect(title).toContain('white-space:nowrap');
  });

  it('fits the picture scroller exactly inside its box', () => {
    const scroller = rule(graphCss, '#memory-graph-root .mg-scroll');
    expect(scroller).toContain('margin:0');
    expect(scroller).toContain('padding:0');
    expect(scroller).not.toContain('-4px');
  });

  it('gives the canvas a wide document column that really contains it', () => {
    const page = rule(graphCss, '.doc.doc-wide:has(> #memory-graph-root)');
    expect(page).toContain('padding:0');
    const root = rule(graphCss, '#memory-graph-root');
    expect(root).toContain('width:100%');
    expect(root).not.toContain('transform');
  });

  it('lets the legend text shrink beside its glyph', () => {
    expect(rule(graphCss, '#memory-graph-root .mg-legend li>span')).toContain('min-width:0');
  });

  it('sizes the empty ghost columns to their headings', () => {
    expect(rule(graphCss, '#memory-graph-root .mg-empty-col')).toContain('flex-basis:auto');
    const title = rule(graphCss, '#memory-graph-root .mg-empty-col .mg-col-title');
    expect(title).toContain('overflow:hidden');
    expect(title).toContain('text-overflow:ellipsis');
    expect(title).toContain('white-space:nowrap');
    const narrow = media(graphCss, '@media (max-width:700px)');
    expect(narrow).toContain('#memory-graph-root .mg-empty-ghost{display:none}');
    expect(narrow).toContain('#memory-graph-root .mg-empty{grid-template-columns:minmax(0,1fr)}');
  });

  it('ellipsizes the provenance removal button rather than breaking its label', () => {
    const remove = rule(graphCss, '#memory-graph-root .mg-remove');
    expect(remove).toContain('max-width:100%');
    expect(remove).toContain('white-space:nowrap');
    expect(remove).toContain('text-overflow:ellipsis');
  });

  it('wraps the provenance eyebrow and step rows', () => {
    expect(rule(graphCss, '#memory-graph-root .mg-eyebrow')).toContain('flex-wrap:wrap');
    expect(rule(graphCss, '#memory-graph-root .mg-steps-name')).toContain('flex-wrap:wrap');
    expect(rule(graphCss, '#memory-graph-root .mg-steps-name time')).toContain('white-space:nowrap');
  });
});

describe('memory loop text fit', () => {
  it('breaks prose anywhere on the loop root and the server maintenance tile', () => {
    expect(rule(loopCss, '#memory-loop-root .ml')).toContain('overflow-wrap:anywhere');
    expect(rule(loopCss, '.ml-maint')).toContain('overflow-wrap:anywhere');
  });

  it('keeps loop mono values and figures on one line', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-mono')).toContain('white-space:nowrap');
    expect(rule(loopCss, '#memory-loop-root .ml-figure')).toContain('white-space:nowrap');
  });

  it('keeps a busy button the same box as its idle self', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-btn.mem-pending')).toContain('position:relative');
    const dot = rule(loopCss, '#memory-loop-root .ml-btn.mem-pending .mem-busy-dot');
    expect(dot).toContain('position:absolute');
    expect(dot).toContain('left:6px');
    expect(dot).toContain('top:50%');
    expect(dot).toContain('margin-top:-4px');
    const labels = rule(loopCss, '#memory-loop-root .ml-btn.mem-pending .mem-btn-labels');
    expect(labels).toContain('transform:translateX(8px)');
    expect(rule(loopCss, '#memory-loop-root .ml-text-btn .mem-btn-labels')).toContain('display:inline-grid');
  });

  it('wraps the four-step strip top row and keeps its labels inside the step', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-step-top')).toContain('flex-wrap:wrap');
    expect(rule(loopCss, '#memory-loop-root .ml-step-index')).toContain('white-space:nowrap');
    const tag = rule(loopCss, '#memory-loop-root .ml-flow .ml-tag');
    expect(tag).toContain('min-width:0');
    expect(tag).toContain('white-space:normal');
    expect(tag).not.toContain('text-overflow:ellipsis');
    const chip = rule(loopCss, '#memory-loop-root .ml-step-top .ml-chip-quiet');
    expect(chip).toContain('max-width:100%');
    expect(chip).toContain('white-space:normal');
    const unit = rule(loopCss, '#memory-loop-root .ml-step-unit');
    expect(unit).toContain('white-space:nowrap');
    expect(unit).toContain('overflow:hidden');
    expect(unit).toContain('text-overflow:ellipsis');
  });

  it('wraps tile heads before their count or filter is squeezed', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-tile-head')).toContain('flex-wrap:wrap');
    expect(rule(loopCss, '#memory-loop-root .ml-tile-count')).toContain('white-space:nowrap');
    expect(rule(loopCss, '#memory-loop-root .ml-filter')).toContain('flex:none');
  });

  it('wraps candidate meta beside its timestamp', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-cand-meta')).toContain('flex-wrap:wrap');
  });

  it('wraps a knowledge row before its actions leave the tile', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-row')).toContain('flex-wrap:wrap');
    const main = rule(loopCss, '#memory-loop-root .ml-row-main');
    expect(main).toContain('flex:1 1 220px');
    expect(main).toContain('min-width:0');
    const actions = rule(loopCss, '#memory-loop-root .ml-row-actions');
    expect(actions).toContain('flex:none');
    expect(actions).toContain('flex-wrap:wrap');
  });

  it('keeps the tab strip inside the tile and scrolling', () => {
    const tabs = rule(loopCss, '#memory-loop-root .ml-tabs');
    expect(tabs).toContain('overflow-x:auto');
    expect(tabs).toContain('min-width:0');
    expect(tabs).toContain('max-width:100%');
  });

  it('wraps the observations subbar before its button is squeezed', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-subbar')).toContain('flex-wrap:wrap');
    expect(rule(loopCss, '#memory-loop-root .ml-subbar .ml-note')).toContain('flex:1 1 220px');
    expect(rule(loopCss, '#memory-loop-root .ml-subbar .ml-btn')).toContain('flex:none');
  });

  it('wraps the maintenance subtitle instead of ellipsizing it', () => {
    const sub = rule(loopCss, '.ml-maint-sub');
    expect(sub).toContain('overflow-wrap:anywhere');
    expect(sub).toContain('flex:1 1 220px');
    expect(sub).not.toContain('text-overflow:ellipsis');
    expect(sub).not.toContain('white-space:nowrap');
    expect(rule(loopCss, '.ml-maint>summary')).toContain('flex-wrap:wrap');
    expect(rule(loopCss, '.ml-maint-row')).toContain('flex-wrap:wrap');
    expect(rule(loopCss, '.ml-maint-form')).toContain('flex-wrap:wrap');
  });

  it('keeps segment labels inside their halves', () => {
    const segment = rule(loopCss, '#memory-loop-root .ml-segment button');
    expect(segment).toContain('min-width:0');
    expect(segment).toContain('white-space:nowrap');
    expect(segment).toContain('overflow:hidden');
    expect(segment).toContain('text-overflow:ellipsis');
  });

  it('wraps a switch below a long label instead of squeezing it', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-switch-row')).toContain('flex-wrap:wrap');
    const label = rule(loopCss, '#memory-loop-root .ml-switch-label');
    expect(label).toContain('flex:1 1 220px');
    expect(label).toContain('min-width:0');
  });

  it('wraps the notice, more and undo rows', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-notice')).toContain('flex-wrap:wrap');
    expect(rule(loopCss, '#memory-loop-root .ml-more')).toContain('flex-wrap:wrap');
    expect(rule(loopCss, '#memory-loop-root .ml-undo')).toContain('flex-wrap:wrap');
    expect(rule(loopCss, '#memory-loop-root .ml-undo>span:first-child')).toContain('flex:1 1 220px');
  });

  it('keeps the excerpt summary inside its column', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-excerpt summary')).toContain('max-width:100%');
  });

  it('keeps an entity chip inside its tile', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-entity')).toContain('max-width:100%');
  });

  it('keeps the dialog title wrapping and its actions wrapping', () => {
    expect(rule(loopCss, '#memory-loop-root .ml-dialog-title')).toContain('overflow-wrap:anywhere');
    expect(rule(loopCss, '#memory-loop-root .ml-dialog-actions')).toContain('flex-wrap');
  });
});
