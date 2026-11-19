// The sales card, the hero of the bento grid, with every state the
// server-rendered one has: disabled, unconfigured (picker flow with the
// manual path fallback), first snapshot, healthy delta,
// stale/locked/unreadable amber with Re-test. Copy and flows follow
// pages.py and sales.py exactly; every action refetches /api/dashboard
// instead of reloading the page. Empty and single-message states are
// composed as one centered row (icon, message, action).
import { useState, type KeyboardEvent } from 'react';
import { postJson } from '../api';
import {
  fileNameOf, rowLine, salesStamp,
} from '../fmt';
import type { DeltaPayload, SalesStatus } from '../types';
import WidgetCard from '../components/WidgetCard';
import Button from '../components/Button';
import EmptyState, { ICON_SHEET } from '../components/EmptyState';

const MAX_EXAMPLE_ROWS = 8;

interface SalesCardProps {
  sales: { enabled: boolean; mode: 'disabled' | 'unconfigured' | 'live'; status: SalesStatus | null };
  // The layout's custom title, when the user renamed the card.
  title?: string;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

/**
 * The added and removed rows of the delta, capped, with a count of the rows left out.
 */
function DeltaRows({ delta }: { delta: DeltaPayload }) {
  const added = delta.added ?? [];
  const removed = delta.removed ?? [];
  const changed = added.length + removed.length;
  if (changed === 0) {
    return <p className="empty">No changes in the last 24 hours.</p>;
  }
  const upRows = added.slice(0, MAX_EXAMPLE_ROWS)
    .map((row, i) => <tr key={`a${i}`}><td><span className="delta up">+</span> {rowLine(row)}</td></tr>);
  const downRows = removed.slice(0, MAX_EXAMPLE_ROWS)
    .map((row, i) => <tr key={`r${i}`}><td><span className="delta down">-</span> {rowLine(row)}</td></tr>);
  const shown = upRows.length + downRows.length;
  return (
    <table className="rows">
      <tbody>
        {upRows}
        {downRows}
        {changed > shown && (
          <tr><td className="empty">+ {changed - shown} more row(s) in the full delta</td></tr>
        )}
      </tbody>
    </table>
  );
}

/**
 * The sales card: the 24-hour row-hash diff, or the paused, unconfigured, first-
 * snapshot, stale and unreadable states.
 *
 * Every action refetches the dashboard rather than reloading the page; onExpired hands
 * a 401 back to the caller.
 */
export default function SalesCard({ sales, title, onRefetch, onExpired }: SalesCardProps) {
  const [note, setNote] = useState('');
  const [manualOpen, setManualOpen] = useState(false);
  const [pathInput, setPathInput] = useState('');
  const [busy, setBusy] = useState(false);
  const heading = title ?? 'Sales, last 24 hours';

  /** Put a message in the card's status line. */
  const show = (text: string) => setNote(text);

  /**
   * Run a request with the busy flag set, returning its result or null when the server
   * could not be reached.
   */
  async function guard<T>(run: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    try {
      return await run();
    } catch {
      return null;
    } finally {
      setBusy(false);
    }
  }

  /**
   * Connect a workbook by path and reload the dashboard; a note says why nothing
   * changed.
   */
  async function connect(path: string) {
    const res = await guard(() => postJson('/sources/excel-watch', { path }));
    if (res === null) {
      show('The dashboard could not reach its own server; nothing was connected.');
      return;
    }
    if (res.status === 401) { onExpired(); return; }
    const data = res.data as { error?: string };
    if (!res.ok || data.error) {
      show(data.error || 'The workbook was not connected; nothing changed.');
      return;
    }
    setNote('');
    setManualOpen(false);
    setPathInput('');
    await onRefetch();
  }

  /**
   * Open the file dialog and connect the chosen workbook; a dialog that never opened
   * falls back to the manual path input.
   */
  async function pick() {
    const res = await guard(() => postJson('/sources/excel-watch/pick'));
    if (res === null) {
      show('The dashboard could not reach its own server; the file dialog was not opened.');
      return;
    }
    if (res.status === 401) { onExpired(); return; }
    const data = res.data as { path?: string | null };
    if (!data.path) {
      setManualOpen(true);
      show('The file dialog did not open. Type the workbook path below and press Connect.');
      return;
    }
    await connect(data.path);
  }

  /** Connect the typed path, or say that the field is empty. */
  function manual() {
    const path = pathInput.trim();
    if (!path) {
      show('Type the full path to the workbook first.');
      return;
    }
    void connect(path);
  }

  /** Connect on Enter in the path field. */
  function onInputKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault();
      manual();
    }
  }

  /** Re-test the workbook read and reload the dashboard. */
  async function retest() {
    const res = await guard(() => postJson('/sources/excel-watch/retest'));
    if (res === null) {
      show('The dashboard could not reach its own server; the re-test did not run.');
      return;
    }
    if (res.status === 401) { onExpired(); return; }
    await onRefetch();
  }

  const status = sales.status;

  if (sales.mode === 'disabled') {
    return (
      <WidgetCard
        title={heading}
        span="span-7"
        footLines={2}
        sparse
        stamp={{ fresh: false, text: 'Paused' }}
        menuItems={[{ label: 'Open settings', href: '/settings' }]}
        foot="No ingestion while off. Your snapshots stay on this machine."
      >
        <EmptyState
          icon={ICON_SHEET}
          action={<Button tone="primary" href="/settings">Turn it back on</Button>}
        >
          Sales watching is turned off in settings. Nothing is being read from
          the workbook right now.
        </EmptyState>
      </WidgetCard>
    );
  }

  if (sales.mode === 'unconfigured' || status === null || !status.configured) {
    return (
      <WidgetCard
        title={heading}
        span="span-7"
        footLines={2}
        sparse
        stamp={{ fresh: false, text: 'Not connected' }}
        menuItems={[
          { label: 'Connect a workbook', onSelect: () => void pick() },
          { label: 'Open settings', href: '/settings' },
        ]}
        foot="Read-only: the file is copied before parsing, never opened in place."
      >
        <EmptyState
          icon={ICON_SHEET}
          action={(
            <Button tone="primary" onClick={pick} disabled={busy}>
              Connect a workbook
            </Button>
          )}
        >
          No workbook is connected yet, so there is nothing to show here. Once
          one is connected, this card reports what changed in the file over the
          last 24 hours.
        </EmptyState>
        {note ? <div className="alert" role="status">{note}</div> : null}
        {manualOpen && (
          <div className="well">
            <input
              className="well-input"
              type="text"
              placeholder="Full path to the .xlsx or .xlsm workbook"
              aria-label="Workbook path"
              value={pathInput}
              onChange={(e) => setPathInput(e.target.value)}
              onKeyDown={onInputKey}
            />
            <button className="btn btn-primary" type="button" onClick={manual} disabled={busy}>
              Connect
            </button>
          </div>
        )}
      </WidgetCard>
    );
  }

  const stamp = salesStamp(status.state, status.last_ok_ts);
  const amber = status.state === 'stale' || status.state === 'locked' || status.state === 'unreadable';
  const delta = status.delta;
  const added = delta?.added?.length ?? 0;
  const removed = delta?.removed?.length ?? 0;
  const changed = added + removed;

  let body;
  if (status.state === 'healthy') {
    body = (
      <div className="sales-hero">
        <div className="kpi">
          <div className="label">Rows changed, 24 h</div>
          {delta ? (
            <>
              <div className="value">{changed.toLocaleString('en-US')}</div>
              <div className="sub">Row-hash diff against the snapshot from 24 hours ago</div>
              {changed > 0 ? (
                <div className="kpi-split">
                  <span className="kpi-chip up">+{added} added</span>
                  <span className="kpi-chip down">-{removed} removed</span>
                </div>
              ) : null}
            </>
          ) : (
            <>
              <div className="value">Not reported</div>
              <div className="sub">The server sent no row-hash diff for this snapshot, so no change count is shown.</div>
            </>
          )}
        </div>
        <div className="sales-delta">
          {delta ? <DeltaRows delta={delta} /> : null}
        </div>
      </div>
    );
  } else if (status.state === 'first') {
    body = (
      <EmptyState icon={ICON_SHEET}>
        First snapshot taken. The 24-hour view starts with the next poll;
        nothing is invented in the meantime.
      </EmptyState>
    );
  } else if (status.state === 'stale') {
    body = (
      <>
        <div className="alert" role="status"><span>
          This data is old, so it is shown as stale rather than current.
          Re-test to refresh it now.
        </span></div>
        <Button className="btn-start" onClick={retest} disabled={busy}>Re-test now</Button>
        {note ? <div className="alert" role="status">{note}</div> : null}
      </>
    );
  } else {
    body = (
      <>
        <div className="alert" role="status"><span>{status.cause}</span></div>
        <Button className="btn-start" onClick={retest} disabled={busy}>Re-test now</Button>
        {note ? <div className="alert" role="status">{note}</div> : null}
      </>
    );
  }

  return (
    <WidgetCard
      title="Sales, last 24 hours"
      span="span-7"
      footLines={2}
      sparse={status.state !== 'healthy'}
      stamp={stamp}
      amber={amber}
      menuItems={[
        { label: 'Re-test now', onSelect: retest, disabled: busy },
        { label: 'Open settings', href: '/settings' },
      ]}
      foot={`Watches ${fileNameOf(status.path)}, hourly, read-only. The file is copied before parsing, never opened in place.`}
    >
      {body}
    </WidgetCard>
  );
}
