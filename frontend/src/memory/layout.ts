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
  { id: 'from', title: 'Came from', kinds: ['origin', 'source'], weight: 1.5 },
  { id: 'fact', title: 'Facts', kinds: ['fact'], weight: 2.4 },
  { id: 'observation', title: 'Observations', kinds: ['observation'], weight: 1.05 },
  { id: 'entity', title: 'Entities', kinds: ['entity'], weight: 1.1 },
];

export const ROW = 32;
export const PILL = 24;
export const GAP = 40;
export const TOP = 8;

export interface Placed {
  node: GraphNode;
  column: number;
  x: number;
  y: number; // pill center
  width: number;
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

export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[], width: number): Layout {
  const present = COLUMNS.filter((column) => nodes.some((node) => column.kinds.includes(node.kind)));
  const units = present.reduce((sum, column) => sum + column.weight, 0) || 1;
  const usable = Math.max(width - GAP * Math.max(present.length - 1, 0), 120);
  let cursor = 0;
  const columns = present.map((column) => {
    const columnWidth = (usable * column.weight) / units;
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
  facts.forEach((node, index) => {
    const entry = columns[factIndex];
    placed.set(node.id, { node, column: factIndex, x: entry.x, width: entry.width, y: TOP + ROW * index + ROW / 2 });
  });

  let height = TOP + ROW * facts.length;
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
    let floor = TOP + ROW / 2;
    for (const item of want) {
      const y = Math.max(Number.isFinite(item.target) ? item.target : floor, floor);
      placed.set(item.node.id, { node: item.node, column: columnIndex, x: entry.x, width: entry.width, y });
      floor = y + ROW;
    }
    height = Math.max(height, floor - ROW / 2 + TOP);
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

// The label that fits a pill: about 6.2px a character at 12px Geist,
// less the glyph and padding. The full text rides the node's <title>
// and the provenance panel.
export function fitLabel(label: string, width: number): string {
  const room = Math.max(Math.floor((width - 32) / 6.2), 4);
  return label.length <= room ? label : `${label.slice(0, room - 1).trimEnd()}\u2026`;
}
