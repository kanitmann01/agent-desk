export type CellKind = 'tracker' | 'digest' | 'watch' | 'health' | 'plugin';

const TRACKER = new Set([
  'excel-report', 'week-load', 'sales-delta-widget', 'budget-burn',
  'revenue-vs-target', 'kpi-scorecard',
]);
const WATCH = new Set([
  'page-watch', 'competitor-watch', 'source-ledger', 'reconciliation-watch',
  'follow-up-watch', 'vip-watch',
]);
const HEALTH = new Set([
  'plugin-health', 'compliance-posture', 'audit-digest', 'update-radar',
]);

/**
 * The cell kind for a plugin id, ignoring a ~variant suffix.
 *
 * A plugin that names no known kind is its own plain kind, never a digest:
 * an unknown plugin must not borrow another family's name.
 */
export function pluginKind(id: string): CellKind {
  const base = id.split('~')[0];
  if (TRACKER.has(base)) return 'tracker';
  if (WATCH.has(base)) return 'watch';
  if (HEALTH.has(base)) return 'health';
  return 'plugin';
}

/** The one uppercase tag a cell of this kind carries. */
export function kindTag(kind: CellKind): string {
  if (kind === 'tracker') return 'TRACKER';
  if (kind === 'watch') return 'PAGE WATCH';
  if (kind === 'health') return 'DESK HEALTH';
  if (kind === 'plugin') return 'PLUGIN';
  return 'DIGEST';
}
