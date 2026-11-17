export type CellKind = 'tracker' | 'digest' | 'watch' | 'health';

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

export function pluginKind(id: string): CellKind {
  const base = id.split('~')[0];
  if (TRACKER.has(base)) return 'tracker';
  if (WATCH.has(base)) return 'watch';
  if (HEALTH.has(base)) return 'health';
  return 'digest';
}

export function kindTag(kind: CellKind): string {
  if (kind === 'tracker') return 'TRACKING';
  if (kind === 'watch') return 'WATCH';
  if (kind === 'health') return 'DESK';
  return 'DIGEST';
}
