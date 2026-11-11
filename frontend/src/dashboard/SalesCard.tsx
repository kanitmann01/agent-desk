// The sales card, every state the server-rendered one has: disabled,
// unconfigured (picker flow with the manual path fallback), first
// snapshot, healthy delta, stale/locked/unreadable amber with Re-test.
// Copy and flows follow pages.py and sales.py exactly; every action
// refetches /api/dashboard instead of reloading the page.
import { useState, type KeyboardEvent } from 'react';
import { postJson } from '../api';
import {
  fileNameOf, rowLine, salesStamp,
} from '../fmt';
import type { DeltaPayload, SalesStatus } from '../types';
import WidgetCard from '../components/WidgetCard';
import ShinyButton from '../components/ShinyButton';
import ClickSpark from '../vendor/reactbits/ClickSpark';
import CountUp from '../vendor/reactbits/CountUp';

const MAX_EXAMPLE_ROWS = 8;

interface SalesCardProps {
  sales: { enabled: boolean; mode: 'disabled' | 'unconfigured' | 'live'; status: SalesStatus | null };
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

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

export default function SalesCard({ sales, onRefetch, onExpired }: SalesCardProps) {
  const [note, setNote] = useState('');
  const [manualOpen, setManualOpen] = useState(false);
  const [pathInput, setPathInput] = useState('');
  const [busy, setBusy] = useState(false);

  const show = (text: string) => setNote(text);

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

  function manual() {
    const path = pathInput.trim();
    if (!path) {
      show('Type the full path to the workbook first.');
      return;
    }
    void connect(path);
  }

  function onInputKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault();
      manual();
    }
  }

  async function retest() {
    const res = await guard(() => postJson('/sources/excel-watch/retest'));
    if (res === null) return;
    if (res.status === 401) { onExpired(); return; }
    await onRefetch();
  }

  const status = sales.status;

  if (sales.mode === 'disabled') {
    return (
      <WidgetCard
        title="Sales, last 24 hours"
        col="col-7"
        stamp={{ fresh: false, text: 'Paused' }}
        foot="No ingestion while off. Your snapshots stay on this machine."
      >
        <div className="well"><p className="q">
          Sales watching is turned off in settings. Nothing is being read from
          the workbook right now.
        </p></div>
        <a className="btn btn-primary btn-start" href="/settings">Turn it back on</a>
      </WidgetCard>
    );
  }

  if (sales.mode === 'unconfigured' || status === null || !status.configured) {
    return (
      <WidgetCard
        title="Sales, last 24 hours"
        col="col-7"
        stamp={{ fresh: false, text: 'Not connected' }}
        foot="Read-only: the file is copied before parsing, never opened in place."
      >
        <div className="well"><p className="q">
          No workbook is connected yet, so there is nothing to show here. Once
          one is connected, this card reports what changed in the file over the
          last 24 hours.
        </p></div>
        <ClickSpark sparkColor="#14594E" sparkSize={10} sparkRadius={26} sparkCount={8} duration={500}>
          <ShinyButton onClick={pick} disabled={busy} className="btn-start">Connect a workbook</ShinyButton>
        </ClickSpark>
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
  const changed = (status.delta?.added?.length ?? 0) + (status.delta?.removed?.length ?? 0);

  let body;
  if (status.state === 'healthy') {
    body = (
      <>
        <div className="kpi">
          <div>
            <div className="label">Rows changed, 24 h</div>
            <div className="value">
              <CountUp to={changed} duration={0.9} separator="," />
            </div>
            <div className="sub">Row-hash diff against the snapshot from 24 hours ago</div>
          </div>
        </div>
        {status.delta ? <DeltaRows delta={status.delta} /> : null}
      </>
    );
  } else if (status.state === 'first') {
    body = (
      <div className="well"><p className="q">
        First snapshot taken. The 24-hour view starts with the next poll;
        nothing is invented in the meantime.
      </p></div>
    );
  } else if (status.state === 'stale') {
    body = (
      <>
        <div className="alert" role="status"><span>
          This data is old, so it is shown as stale rather than current.
          Re-test to refresh it now.
        </span></div>
        <button className="btn btn-secondary btn-start" type="button" onClick={retest} disabled={busy}>
          Re-test now
        </button>
      </>
    );
  } else {
    body = (
      <>
        <div className="alert" role="status"><span>{status.cause}</span></div>
        <button className="btn btn-secondary btn-start" type="button" onClick={retest} disabled={busy}>
          Re-test now
        </button>
      </>
    );
  }

  return (
    <WidgetCard
      title="Sales, last 24 hours"
      col="col-7"
      stamp={stamp}
      amber={amber}
      foot={`Watches ${fileNameOf(status.path)}, hourly, read-only. The file is copied before parsing, never opened in place.`}
    >
      {body}
    </WidgetCard>
  );
}
