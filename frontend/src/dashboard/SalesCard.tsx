// The sales card, the hero of the bento grid, with every state the
// server-rendered one has: disabled, unconfigured (picker flow with the
// manual path fallback), first snapshot, healthy delta,
// stale/locked/unreadable amber with Re-test. Copy and flows follow
// pages.py and sales.py exactly; every action refetches /api/dashboard
// instead of reloading the page. Empty and single-message states are
// composed as one centered row (icon, message, action). The connect
// walk itself is the shared useWorkbookConnect hook.
import { useState } from 'react';
import { postJson } from '../api';
import {
  fileNameOf, rowLine, salesStamp,
} from '../fmt';
import type { DeltaPayload, SalesStatus } from '../types';
import WidgetCard from '../components/WidgetCard';
import Button from '../components/Button';
import { PhaseLine } from '../components/feedback';
import { useBusy } from '../components/useBusy';
import EmptyState, { ICON_SHEET } from '../components/EmptyState';
import { useWorkbookConnect } from './useWorkbookConnect';

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
  const workbook = useWorkbookConnect(onExpired, onRefetch);
  const { note, setNote, busy, busyKind, manualOpen, pathInput, setPathInput, pick, connect, onPathKey } = workbook;
  const [retestBusy, setRetestBusy] = useState(false);
  const heading = title ?? 'Sales, last 24 hours';
  // Nothing shows under 100 ms; the control that started the work carries
  // its own continuous verb, and the card names the phase in one line.
  const pickShown = useBusy(busy && busyKind === 'pick');
  const connectShown = useBusy(busy && busyKind === 'connect');
  const retestShown = useBusy(retestBusy);
  const connectPhase = busyKind === 'pick' ? 'Opening the file dialog' : 'Connecting the workbook';

  /** Connect the typed path, or say that the field is empty. */
  function manual() {
    const path = pathInput.trim();
    if (!path) {
      setNote('Type the full path to the workbook first.');
      return;
    }
    void connect(path);
  }

  /** Re-test the workbook read and reload the dashboard. */
  async function retest() {
    setRetestBusy(true);
    setNote('');
    let res;
    try {
      res = await postJson('/sources/excel-watch/retest');
    } catch {
      setRetestBusy(false);
      setNote('The dashboard could not reach its own server; the re-test did not run. Try again.');
      return;
    }
    if (res.status === 401) { setRetestBusy(false); onExpired(); return; }
    if (!res.ok) {
      setRetestBusy(false);
      setNote('The re-test did not run; try again in a moment.');
      return;
    }
    // The phase line holds until the fresh payload lands.
    await onRefetch();
    setRetestBusy(false);
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
          { label: 'Connect a workbook', onSelect: () => void pick(), disabled: busy },
          { label: 'Open settings', href: '/settings' },
        ]}
        foot="Read-only: the file is copied before parsing, never opened in place."
      >
        {busy ? <PhaseLine active text={connectPhase} phaseKey={busyKind ?? ''} /> : null}
        <div className={busy ? 'w-body-stack region-busy' : 'w-body-stack'} aria-busy={busy ? 'true' : undefined}>
          <EmptyState
            icon={ICON_SHEET}
            action={(
              <Button
                tone="primary"
                onClick={() => void pick()}
                disabled={busy}
                pending={pickShown}
                pendingLabel="Opening..."
              >
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
                onKeyDown={onPathKey}
              />
              <Button
                tone="primary"
                onClick={manual}
                disabled={busy}
                pending={connectShown}
                pendingLabel="Connecting..."
              >
                Connect
              </Button>
            </div>
          )}
        </div>
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
        <Button
          className="btn-start"
          onClick={retest}
          disabled={retestBusy}
          pending={retestShown}
          pendingLabel="Re-testing..."
        >
          Re-test now
        </Button>
        {note ? <div className="alert" role="status">{note}</div> : null}
      </>
    );
  } else {
    body = (
      <>
        <div className="alert" role="status"><span>{status.cause}</span></div>
        <Button
          className="btn-start"
          onClick={retest}
          disabled={retestBusy}
          pending={retestShown}
          pendingLabel="Re-testing..."
        >
          Re-test now
        </Button>
        {note ? <div className="alert" role="status">{note}</div> : null}
      </>
    );
  }

  return (
    <WidgetCard
      title={heading}
      span="span-7"
      footLines={2}
      sparse={status.state !== 'healthy'}
      stamp={stamp}
      amber={amber}
      menuItems={[
        { label: 'Re-test now', onSelect: retest, disabled: retestBusy },
        { label: 'Open settings', href: '/settings' },
      ]}
      foot={`Watches ${fileNameOf(status.path)}, hourly, read-only. The file is copied before parsing, never opened in place.`}
    >
      {retestBusy ? <PhaseLine active text="Re-testing the workbook" /> : null}
      <div className={retestBusy ? 'w-body-stack region-busy' : 'w-body-stack'} aria-busy={retestBusy ? 'true' : undefined}>
        {body}
      </div>
    </WidgetCard>
  );
}
