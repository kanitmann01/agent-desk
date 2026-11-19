// The words the graph uses, in one place so the list view, the panel
// and the tests agree.
import type { EdgeType, GraphNode, StepId } from './types';
import type { GlyphKind } from './Glyph';

export const STEP_LABEL: Record<StepId, string> = {
  retain: 'Retain',
  extract: 'Extract',
  approve: 'Approve',
  store: 'Store',
  link: 'Link',
  reflect: 'Reflect',
};

export const STEP_GLYPH: Record<StepId, GlyphKind> = {
  retain: 'source',
  extract: 'candidate',
  approve: 'origin',
  store: 'fact',
  link: 'entity',
  reflect: 'observation',
};

/** The count and noun under a pipeline step; extract also reports waiting rows. */
export function stepUnit(step: StepId, count: number, waiting = 0): string {
  const plural = (noun: string) => `${count} ${noun}${count === 1 ? '' : 's'}`;
  switch (step) {
    case 'retain':
      return plural('excerpt');
    case 'extract':
      return `${count} kept${waiting ? ` · ${waiting} waiting` : ''}`;
    case 'approve':
      return `${count} accepted`;
    case 'store':
      return plural('fact');
    case 'link':
      return count === 1 ? '1 entity' : `${count} entities`;
    case 'reflect':
      return plural('observation');
  }
}

/** The glyph for a node: experience facts draw their own, every other node its kind. */
export function glyphFor(node: GraphNode): GlyphKind {
  if (node.kind === 'fact' && node.factKind === 'experience') return 'experience';
  return node.kind;
}

/** The kind label for a node, with entity type or confidence appended. */
export function kindWord(node: GraphNode): string {
  switch (node.kind) {
    case 'origin':
      return 'Writer';
    case 'source':
      return 'Retained excerpt';
    case 'fact':
      return node.factKind === 'experience' ? 'Experience' : 'World fact';
    case 'entity':
      return `Entity · ${node.entityType ?? 'other'}`;
    case 'observation':
      return `Observation · ${(node.confidence ?? 0).toFixed(2)} confidence`;
  }
}

// How a neighbour relates to the selected node, read from the edge's
// direction.
/** The edge label as read from the selected node, in the active or passive voice. */
export function relation(type: EdgeType, selectedIsSource: boolean): string {
  switch (type) {
    case 'wrote':
      return selectedIsSource ? 'Wrote' : 'Written by';
    case 'extracted':
      return selectedIsSource ? 'Extracted into' : 'Extracted from';
    case 'mentions':
      return selectedIsSource ? 'Mentions' : 'Mentioned in';
    case 'cites':
      return selectedIsSource ? 'Cites' : 'Cited by';
    case 'temporal':
      return 'Close in time';
    case 'semantic':
      return 'Similar meaning';
  }
}

const formatter = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

/**
 * The moment as "27 Jan, 14:05" in the viewer's locale, or "" when it is absent.
 *
 * ts is epoch seconds, not milliseconds.
 */
export function when(ts: number | null | undefined): string {
  if (ts === null || ts === undefined) return '';
  return formatter.format(new Date(ts * 1000));
}
