// The reusable selection surface: a preview grid (headers, rows) with
// row picking shared by every gesture. A click toggles a row; dragging
// across rows selects or deselects the whole sweep, respecting how the
// sweep started; shift-click fills the inclusive range from the last
// anchor; Select all and Clear bound the selection; a live count always
// shows what is tracked. Column assignment stays header-click based, so
// a future data kind only supplies a different preview.
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import Button from './Button';

// A preview cell that is a plain number ("18000", "-1250.5") reads as an
// amount: right-aligned mono with thousands separators. Anything else
// (names, dates, codes with leading zeros) is shown as the sheet has it.
const NUMBER = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const AMOUNT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

/**
 * Preview cell as display text, plus whether it reads as an amount.
 *
 * Amounts are grouped with separators; anything else is trimmed and shown
 * exactly as the sheet has it.
 */
function cellView(value: string | undefined): { text: string; numeric: boolean } {
  const raw = (value ?? '').trim();
  if (NUMBER.test(raw)) return { text: AMOUNT.format(Number(raw)), numeric: true };
  return { text: raw, numeric: false };
}

/** True when every filled cell of a column is a plain number; blanks are skipped. */
function numericColumn(rows: string[][], column: number): boolean {
  const filled = rows.map((row) => (row[column] ?? '').trim()).filter(Boolean);
  return filled.length > 0 && filled.every((value) => NUMBER.test(value));
}

/** Selection as ascending indexes, the form `selected` is held in. */
function ordered(values: Set<number>): number[] {
  return [...values].sort((a, b) => a - b);
}

export interface GridPreview {
  headers: string[];
  rows: string[][];
  sheet?: string;
}

interface RowSelectGridProps {
  preview: GridPreview;
  selected: number[];
  onSelectedChange: (rows: number[]) => void;
  onAssignHeader?: (header: string) => void;
  valueColumn?: string;
  labelColumn?: string;
}

// One pointer sweep: the rows between the anchor and the pointer take
// the mode the sweep started with (select from an unselected anchor,
// deselect from a selected one); everything outside keeps the snapshot
// from the sweep's start, so backing up mid-drag is honest.
interface Sweep {
  anchor: number;
  mode: boolean;
  base: number[];
}

/**
 * Preview grid with row picking: a click toggles, a drag sweeps, and a
 * shift-click fills the range from the last anchor.
 *
 * `selected` is controlled and `onSelectedChange` reports ascending indexes;
 * `onAssignHeader` turns the headers into buttons, and `valueColumn` and
 * `labelColumn` mark the two columns a data kind reads.
 */
export default function RowSelectGrid({
  preview, selected, onSelectedChange, onAssignHeader, valueColumn = '', labelColumn = '',
}: RowSelectGridProps) {
  const [anchor, setAnchor] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const sweep = useRef<Sweep | null>(null);

  useEffect(() => {
    if (!dragging) return undefined;
    /** End the sweep when the pointer is released or cancelled. */
    const end = () => {
      sweep.current = null;
      setDragging(false);
    };
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
    return () => {
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
    };
  }, [dragging]);

  /** True when the row is part of the tracked selection. */
  const isSelected = (index: number) => selected.includes(index);

  /**
   * Extend the live sweep from its anchor to this row.
   *
   * Rows outside the span go back to the snapshot taken when the sweep
   * started, so backing up mid-drag deselects honestly.
   */
  function sweepTo(index: number) {
    const session = sweep.current;
    if (!session) return;
    const next = new Set(session.base);
    for (let i = Math.min(session.anchor, index); i <= Math.max(session.anchor, index); i += 1) {
      if (session.mode) next.add(i);
      else next.delete(i);
    }
    onSelectedChange(ordered(next));
  }

  /** Toggle one row, ending any sweep and making it the new anchor. */
  function toggleOne(index: number) {
    sweep.current = null;
    setDragging(false);
    onSelectedChange(isSelected(index)
      ? selected.filter((item) => item !== index)
      : ordered(new Set([...selected, index])));
    setAnchor(index);
  }

  /**
   * Apply the inclusive range from the anchor to this row.
   *
   * The range selects when this row is unselected and clears when it is
   * selected; the anchor then moves here.
   */
  function fillRange(index: number) {
    const from = anchor ?? index;
    const add = !isSelected(index);
    const next = new Set(selected);
    for (let i = Math.min(from, index); i <= Math.max(from, index); i += 1) {
      if (add) next.add(i);
      else next.delete(i);
    }
    onSelectedChange(ordered(next));
    setAnchor(index);
  }

  /**
   * Start a sweep on this row, or fill a range when shift is held.
   *
   * Only the primary button starts a sweep, and presses on the row's own
   * checkbox or links belong to those controls; the sweep's mode follows
   * whether the anchor was already selected.
   */
  function onRowPointerDown(event: ReactPointerEvent<HTMLTableRowElement>, index: number) {
    if (event.shiftKey) {
      sweep.current = null;
      setDragging(false);
      fillRange(index);
      return;
    }
    if (event.button !== 0) return;
    // The checkbox owns its own toggle; the gestures start on the cells.
    if ((event.target as HTMLElement).closest('input, button, a')) return;
    const base = selected;
    sweep.current = { anchor: index, mode: !base.includes(index), base };
    setDragging(true);
    setAnchor(index);
    sweepTo(index);
  }

  const all = preview.rows.map((_row, index) => index);

  return (
    <>
      <div className="setup-toolbar">
        <div className="setup-actions">
          <Button tone="secondary" className="btn-sm" onClick={() => onSelectedChange(all)} disabled={all.length === 0 || selected.length === all.length}>Select all</Button>
          <Button tone="secondary" className="btn-sm" onClick={() => onSelectedChange([])} disabled={selected.length === 0}>Clear</Button>
        </div>
        <p className="pick-count mono" aria-live="polite">{selected.length}/{preview.rows.length} rows</p>
      </div>
      <div className="setup-table-wrap" tabIndex={0} aria-label={`${preview.sheet ?? 'Preview'}, first ${preview.rows.length} rows`}>
        <table className="preview-grid" style={{ userSelect: 'none' }}>
          <caption className="sr-only">{preview.sheet ?? 'Preview'}, first {preview.rows.length} rows</caption>
          <thead>
            <tr>
              <th scope="col" className="row-num">#</th>
              <th scope="col" className="row-pick"><span className="sr-only">Track</span></th>
              {preview.headers.map((header, column) => {
                const numeric = numericColumn(preview.rows, column);
                const cls = [header === valueColumn ? 'is-value' : header === labelColumn ? 'is-label' : '', numeric ? 'num' : ''].filter(Boolean).join(' ');
                return (
                  <th key={header} scope="col" className={cls}>
                    {onAssignHeader ? (
                      <button type="button" onClick={() => onAssignHeader(header)}>{header}</button>
                    ) : (
                      <span style={{ display: 'block', padding: '0 14px' }}>{header}</span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, index) => {
              const picked = isSelected(index);
              return (
                <tr
                  key={index}
                  className={picked ? 'is-picked' : ''}
                  aria-selected={picked}
                  onPointerDown={(event) => onRowPointerDown(event, index)}
                  onPointerEnter={() => sweepTo(index)}
                  onPointerMove={(event) => {
                    if ((event.target as HTMLElement).closest('tr') === event.currentTarget) sweepTo(index);
                  }}
                >
                  <td className="row-num">{index + 1}</td>
                  <td className="row-pick">
                    <input
                      type="checkbox"
                      className="check-box"
                      aria-label={`Track row ${index + 1}`}
                      checked={picked}
                      onChange={() => toggleOne(index)}
                    />
                  </td>
                  {preview.headers.map((header, column) => {
                    const view = cellView(row[column]);
                    const cls = [header === valueColumn ? 'is-value' : header === labelColumn ? 'is-label' : '', view.numeric ? 'num' : ''].filter(Boolean).join(' ');
                    return <td key={header} className={cls}>{view.text}</td>;
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
