// Turns a workbook hash-diff into the morning brief: one net figure and
// one row per deal. An edited row arrives once in `added` and once in
// `removed`; those pair into a single change. A trailing "- 12" is the
// sample workbook's row index, not a name, so it is never shown. Some CRM
// exports spell the dash as an em dash, so the regex strips both; the
// escape keeps that character out of this tree.
import type { DeltaPayload, DeskCheckSummary } from '../types';

const ROW_INDEX = /(?:\u2014|-)\s*\d+$/;

export type MoverKind = 'changed' | 'added' | 'removed';

export interface Mover {
  kind: MoverKind;
  /** The deal name with its close date, distinct even when titles repeat. */
  name: string;
  /** The deal name alone, as the workbook spells it. */
  deal: string;
  /** The close date as "27 Jan", or "". */
  close: string;
  region: string;
  stage: string;
  previousName: string | null;
  meta: string;
  oldAmount: number | null;
  newAmount: number | null;
  delta: number;
}

export const MOVER_CAP = 5;

// The desk check's foot line under the health matrix: one finding when
// something wants attention, nothing when the desk is quiet. The label is
// the whole line; the link goes to every finding, on the settings page.
export interface DeskCheckAlert {
  label: string;
  href: string;
}

/** The health cell's desk-check foot line, or null when nothing wants attention. */
export function deskCheckAlert(
  deskCheck: DeskCheckSummary | null | undefined,
): DeskCheckAlert | null {
  if (!deskCheck || deskCheck.attention <= 0 || !deskCheck.top) return null;
  return {
    label: `Desk check: ${deskCheck.top.title} · Open`,
    href: '/settings#desk-check',
  };
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** A workbook date cell as "27 Jan", or "" when the value is not an ISO date. */
function shortDate(value: unknown): string {
  if (typeof value !== 'string') return '';
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return '';
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${Number(match[3])} ${month}` : '';
}

/**
 * The deal name with its close date, e.g. "Acme, 27 Jan".
 *
 * An empty name cell reads as "Row".
 */
export function dealName(row: unknown[]): string {
  const base = String(row[0] ?? '').replace(ROW_INDEX, '').trim() || 'Row';
  const when = shortDate(row[4]);
  return when ? `${base}, ${when}` : base;
}

/** The deal name alone, without the sample workbook's trailing row index. */
export function dealBase(row: unknown[]): string {
  return String(row[0] ?? '').replace(ROW_INDEX, '').trim() || 'Row';
}

/** A workbook cell as trimmed text; null and undefined become an empty string. */
function cellText(value: unknown): string {
  return value == null ? '' : String(value).trim();
}

/** The deal, close, region and stage columns of a mover row, normalised for display. */
function rowFields(row: unknown[]) {
  return {
    deal: dealBase(row),
    close: shortDate(row[4]),
    region: cellText(row[1]),
    stage: cellText(row[2]),
  };
}

/** Region and stage joined with a middle dot, skipping the cells that are empty. */
function dealMeta(row: unknown[]): string {
  return [row[1], row[2]]
    .map((cell) => (cell == null ? '' : String(cell).trim()))
    .filter(Boolean)
    .join(' · ');
}

/** The amount cell as a finite number, or null when the cell holds anything else. */
function amountOf(row: unknown[]): number | null {
  const value = row[3];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** The name cell as trimmed text, before the row index is stripped. */
function rawName(row: unknown[]): string {
  return String(row[0] ?? '').trim();
}

/**
 * A changed mover built from a row's new and previous values.
 *
 * The delta counts an absent amount as zero, and the previous name is kept
 * only when the visible name changed.
 */
function pair(next: unknown[], prev: unknown[]): Mover {
  const oldAmount = amountOf(prev);
  const newAmount = amountOf(next);
  const nextName = dealName(next);
  const prevName = dealName(prev);
  return {
    kind: 'changed',
    ...rowFields(next),
    name: nextName,
    previousName: prevName !== nextName ? prevName : null,
    meta: dealMeta(next) || dealMeta(prev),
    oldAmount,
    newAmount,
    delta: (newAmount ?? 0) - (oldAmount ?? 0),
  };
}

/** One mover per deal, largest absolute change first. */
export function moversFromDelta(delta: DeltaPayload): Mover[] {
  const removed = [...(delta.removed ?? [])];
  const used = new Set<number>();
  const movers: Mover[] = [];

  /**
   * The index of the first unpaired removed row matching the predicate.
   *
   * The row is marked as paired so a later call cannot match it again.
   */
  function take(match: (row: unknown[]) => boolean): number {
    const index = removed.findIndex((row, i) => !used.has(i) && match(row));
    if (index >= 0) used.add(index);
    return index;
  }

  for (const row of delta.added ?? []) {
    const index = rawName(row)
      ? take((other) => rawName(other) === rawName(row))
      : -1;
    if (index >= 0) {
      movers.push(pair(row, removed[index]));
      continue;
    }
    const amount = amountOf(row);
    movers.push({
      kind: 'added',
      ...rowFields(row),
      name: dealName(row),
      previousName: null,
      meta: dealMeta(row),
      oldAmount: null,
      newAmount: amount,
      delta: amount ?? 0,
    });
  }

  removed.forEach((row, index) => {
    if (used.has(index)) return;
    const amount = amountOf(row);
    movers.push({
      kind: 'removed',
      ...rowFields(row),
      name: dealName(row),
      previousName: null,
      meta: dealMeta(row),
      oldAmount: amount,
      newAmount: null,
      delta: amount == null ? 0 : -amount,
    });
  });

  movers.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || a.name.localeCompare(b.name));
  return movers;
}

/** Added amounts minus removed amounts: the pipeline change, not a row count. */
export function netPipeline(delta: DeltaPayload): number {
  /** The total of these rows' amount cells, counting absent amounts as zero. */
  const sum = (rows: unknown[][] | undefined) =>
    (rows ?? []).reduce((total, row) => total + (amountOf(row) ?? 0), 0);
  return sum(delta.added) - sum(delta.removed);
}

/** A change rounded and grouped for display, with a + or − sign and "0" for zero. */
export function formatSigned(value: number): string {
  const body = Math.abs(Math.round(value)).toLocaleString('en-US');
  if (value > 0) return `+${body}`;
  if (value < 0) return `−${body}`;
  return '0';
}

/** An amount rounded and grouped for display, or "" when it is absent. */
export function formatAmount(value: number | null): string {
  if (value == null) return '';
  return Math.round(value).toLocaleString('en-US');
}

export interface StageNet {
  stage: string;
  net: number;
  deals: number;
}

/**
 * The net change per pipeline stage, in the order the stages first
 * appear in the movers (largest move first). A deal that changed stage
 * counts where it sits now. Rows without a stage group under "Other".
 */
export function netByStage(movers: Mover[]): StageNet[] {
  const order: string[] = [];
  const totals = new Map<string, StageNet>();
  for (const mover of movers) {
    const stage = mover.stage || 'Other';
    let entry = totals.get(stage);
    if (!entry) {
      entry = { stage, net: 0, deals: 0 };
      totals.set(stage, entry);
      order.push(stage);
    }
    entry.net += mover.delta;
    entry.deals += 1;
  }
  return order.map((stage) => totals.get(stage)!);
}

/** "18,850" style, for a figure that may be absent. */
export function formatCompact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 10_000) return `${Math.round(value / 1_000)}k`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(Math.round(value));
}
