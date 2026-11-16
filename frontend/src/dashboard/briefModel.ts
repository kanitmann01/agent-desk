// Turns a workbook hash-diff into the morning brief: one net figure and
// one row per deal. An edited row arrives once in `added` and once in
// `removed`; those pair into a single change. A trailing "— 12" is the
// sample workbook's row index, not a name, so it is never shown.
import type { DeltaPayload } from '../types';

const ROW_INDEX = /(?:—|-)\s*\d+$/;

export type MoverKind = 'changed' | 'added' | 'removed';

export interface Mover {
  kind: MoverKind;
  name: string;
  previousName: string | null;
  meta: string;
  oldAmount: number | null;
  newAmount: number | null;
  delta: number;
}

export const MOVER_CAP = 5;

export function dealName(row: unknown[]): string {
  const raw = String(row[0] ?? '').replace(ROW_INDEX, '').trim();
  return raw || 'Row';
}

export function dealMeta(row: unknown[]): string {
  return [row[1], row[2]]
    .map((cell) => (cell == null ? '' : String(cell).trim()))
    .filter(Boolean)
    .join(' · ');
}

function amountOf(row: unknown[]): number | null {
  const value = row[3];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function rawName(row: unknown[]): string {
  return String(row[0] ?? '').trim();
}

function indexKey(row: unknown[]): string | null {
  const match = rawName(row).match(/(?:—|-)\s*(\d+)$/);
  return match ? match[1] : null;
}

function pair(next: unknown[], prev: unknown[]): Mover {
  const oldAmount = amountOf(prev);
  const newAmount = amountOf(next);
  const nextName = dealName(next);
  const prevName = dealName(prev);
  return {
    kind: 'changed',
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

  function take(match: (row: unknown[]) => boolean): number {
    const index = removed.findIndex((row, i) => !used.has(i) && match(row));
    if (index >= 0) used.add(index);
    return index;
  }

  for (const row of delta.added ?? []) {
    let index = rawName(row)
      ? take((other) => rawName(other) === rawName(row))
      : -1;
    if (index < 0) {
      const key = indexKey(row);
      if (key) index = take((other) => indexKey(other) === key);
    }
    if (index >= 0) {
      movers.push(pair(row, removed[index]));
      continue;
    }
    const amount = amountOf(row);
    movers.push({
      kind: 'added',
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
  const sum = (rows: unknown[][] | undefined) =>
    (rows ?? []).reduce((total, row) => total + (amountOf(row) ?? 0), 0);
  return sum(delta.added) - sum(delta.removed);
}

export function formatSigned(value: number): string {
  const body = Math.abs(Math.round(value)).toLocaleString('en-US');
  if (value > 0) return `+${body}`;
  if (value < 0) return `−${body}`;
  return '0';
}

export function formatAmount(value: number | null): string {
  if (value == null) return '';
  return Math.round(value).toLocaleString('en-US');
}
