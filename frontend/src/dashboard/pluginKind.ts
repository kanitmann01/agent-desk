export type CellKind = 'tracker' | 'digest' | 'watch' | 'health';

// The two plugins this desk ships, by the base id in front of any instance
// suffix. Everything else renders as the digest family.
const TRACKER = new Set(['excel-report']);
const WATCH = new Set(['competitor-watch']);

export function pluginKind(id: string): CellKind {
  const base = id.split('~')[0];
  if (TRACKER.has(base)) return 'tracker';
  if (WATCH.has(base)) return 'watch';
  return 'digest';
}

export function kindTag(kind: CellKind): string {
  if (kind === 'tracker') return 'TRACKING';
  if (kind === 'watch') return 'WATCH';
  if (kind === 'health') return 'DESK';
  return 'DIGEST';
}
