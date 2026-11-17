// The memory graph's pure geometry and graph walks, kept apart from the
// component so they are testable without a DOM.
//
// The picture reads left to right in the order agent-desk makes a
// knowledge point: where it came from (the action that wrote it and the
// excerpt it was extracted from), the fact, the observations reflected
// from facts, and the entities facts are linked to. Facts sit in time
// order, oldest first, so the time links run down one rail; every other
// column orders itself by the average height of the facts it touches
// (one barycenter pass), which keeps most curves short and uncrossed.
import type { GraphEdge, GraphNode, NodeKind } from './types';

export interface Column {
  id: 'from' | 'fact' | 'observation' | 'entity';
  title: string;
  kinds: NodeKind[];
  weight: number;
}

export const COLUMNS: Column[] = [
  { id: 'from', title: 'Came from', kinds: ['origin', 'source'], weight: 1.05 },
  { id: 'fact', title: 'Facts', kinds: ['fact'], weight: 2.1 },
  { id: 'observation', title: 'Observations', kinds: ['observation'], weight: 1.4 },
  { id: 'entity', title: 'Entities', kinds: ['entity'], weight: 1 },
];

// A pill is one or two 16px lines plus 4px above and below; the label
// clamps at two lines. Rows keep an 8px gutter whatever their height.
export const LINE = 16;
export const PILL = LINE + 8;
export const PILL_MAX = LINE * 2 + 8;
export const SPACE = 8;
export const ROW = PILL + SPACE;
export const GAP = 28;
export const TOP = 8;
// Entities are names: their column is as wide as the longest one needs
// (glyph, padding and text), within these bounds, and the other columns
// share what is left by weight.
export const ENTITY_MIN = 96;
export const ENTITY_MAX = 200;
export const LABEL_INSET = 25 + 10;

export interface Placed {
  node: GraphNode;
  column: number;
  x: number;
  y: number; // pill center
  width: number;
  height: number; // pill height
}

export interface Layout {
  columns: { column: Column; x: number; width: number }[];
  placed: Map<string, Placed>;
  height: number;
  width: number;
}

function factTime(node: GraphNode): number {
  return node.occurredTs ?? node.createdTs ?? 0;
}

export interface LayoutOptions {
  // Measured pill heights by node id; a node not measured yet is one line.
  heights?: ReadonlyMap<string, number>;
  // The widest entity label in px, so names fit whole.
  entityText?: number;
}

export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[], width: number, options: LayoutOptions = {}): Layout {
  const heightOf = (id: string) => Math.min(Math.max(options.heights?.get(id) ?? PILL, PILL), PILL_MAX);
  const present = COLUMNS.filter((column) => nodes.some((node) => column.kinds.includes(node.kind)));
  const usable = Math.max(width - GAP * Math.max(present.length - 1, 0), 120);
  const entityWidth = options.entityText === undefined
    ? null
    : Math.min(Math.max(options.entityText + LABEL_INSET, ENTITY_MIN), ENTITY_MAX, usable / 4);
  const shared = present.filter((column) => !(column.id === 'entity' && entityWidth !== null));
  const units = shared.reduce((sum, column) => sum + column.weight, 0) || 1;
  const rest = usable - (present.some((c) => c.id === 'entity') && entityWidth !== null ? entityWidth : 0);
  let cursor = 0;
  const columns = present.map((column) => {
    const columnWidth = column.id === 'entity' && entityWidth !== null ? entityWidth : (rest * column.weight) / units;
    const entry = { column, x: cursor, width: columnWidth };
    cursor += columnWidth + GAP;
    return entry;
  });

  const neighbours = new Map<string, string[]>();
  for (const edge of edges) {
    if (edge.type === 'temporal' || edge.type === 'semantic') continue;
    neighbours.set(edge.source, [...(neighbours.get(edge.source) ?? []), edge.target]);
    neighbours.set(edge.target, [...(neighbours.get(edge.target) ?? []), edge.source]);
  }

  const placed = new Map<string, Placed>();
  const factIndex = columns.findIndex((entry) => entry.column.id === 'fact');
  const facts = nodes
    .filter((node) => node.kind === 'fact')
    .sort((a, b) => factTime(a) - factTime(b) || a.id.localeCompare(b.id));
  let top = TOP;
  for (const node of facts) {
    const entry = columns[factIndex];
    const h = heightOf(node.id);
    placed.set(node.id, { node, column: factIndex, x: entry.x, width: entry.width, height: h, y: top + h / 2 });
    top += h + SPACE;
  }

  let height = top - SPACE + TOP;
  columns.forEach((entry, columnIndex) => {
    if (entry.column.id === 'fact') return;
    const members = nodes.filter((node) => entry.column.kinds.includes(node.kind));
    const want = members.map((node) => {
      const ys = (neighbours.get(node.id) ?? [])
        .map((id) => placed.get(id)?.y)
        .filter((y): y is number => y !== undefined);
      const target = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : Number.POSITIVE_INFINITY;
      // Writers sit above the excerpts they share a column with.
      const rank = node.kind === 'origin' ? 0 : 1;
      return { node, target, rank };
    });
    want.sort((a, b) => a.target - b.target || a.rank - b.rank || a.node.id.localeCompare(b.node.id));
    let floor = TOP; // the top edge the next pill may start at
    for (const item of want) {
      const h = heightOf(item.node.id);
      const y = Math.max(Number.isFinite(item.target) ? item.target : floor + h / 2, floor + h / 2);
      placed.set(item.node.id, { node: item.node, column: columnIndex, x: entry.x, width: entry.width, height: h, y });
      floor = y + h / 2 + SPACE;
    }
    height = Math.max(height, floor - SPACE + TOP);
  });

  return { columns, placed, height: Math.max(height, ROW * 2), width };
}

// Provenance runs one way: writer and excerpt make a fact, a fact makes
// the entity links it carries, facts make the observations that cite
// them. upstream(n) is everything n was made from.
function upstreamOf(id: string, edges: GraphEdge[]): string[] {
  const out: string[] = [];
  for (const edge of edges) {
    if ((edge.type === 'wrote' || edge.type === 'extracted' || edge.type === 'mentions') && edge.target === id) {
      out.push(edge.source);
    } else if (edge.type === 'cites' && edge.source === id) {
      out.push(edge.target);
    }
  }
  return out;
}

// The selection's lineage: the node, everything upstream of it (how it
// was made), and its direct neighbours of any kind (what it touches).
export function lineage(id: string, edges: GraphEdge[]): Set<string> {
  const seen = new Set<string>([id]);
  const queue = [id];
  while (queue.length) {
    const current = queue.shift()!;
    for (const next of upstreamOf(current, edges)) {
      if (!seen.has(next)) {
        seen.add(next);
        queue.push(next);
      }
    }
  }
  for (const edge of edges) {
    if (edge.source === id) seen.add(edge.target);
    if (edge.target === id) seen.add(edge.source);
  }
  return seen;
}

// Keyboard travel: up and down within a column, left and right to the
// nearest node by height in the neighbouring column that has any.
export function neighbourFor(
  layout: Layout,
  fromId: string,
  key: 'ArrowUp' | 'ArrowDown' | 'ArrowLeft' | 'ArrowRight',
): string | null {
  const from = layout.placed.get(fromId);
  if (!from) return null;
  const all = [...layout.placed.values()];
  if (key === 'ArrowUp' || key === 'ArrowDown') {
    const same = all.filter((p) => p.column === from.column).sort((a, b) => a.y - b.y);
    const index = same.findIndex((p) => p.node.id === fromId);
    const next = same[index + (key === 'ArrowDown' ? 1 : -1)];
    return next ? next.node.id : null;
  }
  const step = key === 'ArrowRight' ? 1 : -1;
  for (let column = from.column + step; column >= 0 && column < layout.columns.length; column += step) {
    const candidates = all.filter((p) => p.column === column);
    if (candidates.length) {
      candidates.sort((a, b) => Math.abs(a.y - from.y) - Math.abs(b.y - from.y));
      return candidates[0].node.id;
    }
  }
  return null;
}

// A one-line label for the provenance panel's chips: about 6.2px a
// character at 12px Geist, less the glyph and padding. Graph pills wrap
// instead (see MemoryGraph's label measure).
export function fitLabel(label: string, width: number): string {
  const room = Math.max(Math.floor((width - 32) / 6.2), 4);
  return label.length <= room ? label : `${label.slice(0, room - 1).trimEnd()}\u2026`;
}
