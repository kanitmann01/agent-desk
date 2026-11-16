// The morning brief: one figure, a list of movers, and one decision
// panel. It replaces the three equal cards on the dashboard. Customize
// mode still uses the cards, because reordering needs one object per card.
import { useState, type KeyboardEvent } from 'react';
import { postJson } from '../api';
import { rowLine } from '../fmt';
import type { DashboardData, DeltaPayload } from '../types';
import Button from '../components/Button';

const WALKTHROUGH = '/walkthrough/calendar';

interface BriefProps {
  data: DashboardData;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

function moverName(row: unknown[]): string {
  const line = rowLine(row);
  return line || 'Row';
}

function signedChange(row: unknown[], sign: '+' | '−'): string {
  const amount = row[3];
  if (typeof amount === 'number') return `${sign}${amount.toLocaleString('en-US')}`;
  return sign;
}

function Movers({ delta }: { delta: DeltaPayload }) {
  const ups = (delta.added ?? []).slice(0, 6);
  const downs = (delta.removed ?? []).slice(0, 6);
  if (ups.length + downs.length === 0) {
    return <p className="brief-quiet">No rows changed in the last 24 hours.</p>;
  }
  return (
    <ul className="movers">
      {ups.map((row, i) => (
        <li key={`u${i}`}>
          <span>{moverName(row)}</span>
          <span className="mover up">{signedChange(row, '+')}</span>
        </li>
      ))}
      {downs.map((row, i) => (
        <li key={`d${i}`}>
          <span>{moverName(row)}</span>
          <span className="mover down">{signedChange(row, '−')}</span>
        </li>
      ))}
    </ul>
  );
}

export default function Brief({ data, onRefetch, onExpired }: BriefProps) {
  const [note, setNote] = useState('');
  const [manualOpen, setManualOpen] = useState(false);
  const [pathInput, setPathInput] = useState('');
  const [busy, setBusy] = useState(false);

  const sales = data.sales;
  const status = sales.status;
  const configured = sales.mode === 'live' && Boolean(status?.configured);
  const delta = status?.delta ?? null;
  const added = delta?.added?.length ?? 0;
  const removed = delta?.removed?.length ?? 0;
  const changed = added + removed;
  const salesNeedsConnect = sales.mode !== 'disabled'
    && (sales.mode === 'unconfigured' || status === null || !status.configured);
  const calendarNeedsConnect = data.commitments.mode !== 'live'
    || data.commitments.status?.state === 'empty'
    || data.commitments.status == null;
  const researchNeedsAsk = data.research.lastAnsweredTs == null;
  const decisions = [
    salesNeedsConnect ? 'workbook' : null,
    calendarNeedsConnect ? 'calendar' : null,
    researchNeedsAsk ? 'question' : null,
  ].filter(Boolean);

  async function connect(path: string) {
    setBusy(true);
    try {
      const res = await postJson('/sources/excel-watch', { path });
      if (res.status === 401) { onExpired(); return; }
      const body = res.data as { error?: string };
      if (!res.ok || body.error) {
        setNote(body.error || 'The workbook was not connected; nothing changed.');
        return;
      }
      setNote('');
      setManualOpen(false);
      setPathInput('');
      await onRefetch();
    } catch {
      setNote('The dashboard could not reach its own server; nothing was connected.');
    } finally {
      setBusy(false);
    }
  }

  async function pick() {
    setBusy(true);
    try {
      const res = await postJson('/sources/excel-watch/pick');
      if (res.status === 401) { onExpired(); return; }
      const body = res.data as { path?: string | null };
      if (!body.path) {
        setManualOpen(true);
        setNote('The file dialog did not open. Type the workbook path below and press Connect.');
        return;
      }
      await connect(body.path);
    } catch {
      setNote('The dashboard could not reach its own server; the file dialog was not opened.');
    } finally {
      setBusy(false);
    }
  }

  function onPathKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault();
      const path = pathInput.trim();
      if (path) void connect(path);
    }
  }

  function askFirst() {
    document.querySelector<HTMLTextAreaElement>('.cmd-field')?.focus();
  }

  return (
    <div className={configured ? 'brief' : 'brief brief-empty'}>
      {configured ? (
        <div className="brief-figure">
          <div className="kpi">
            <div className="value">{(delta ? changed : (status?.rowsSeen ?? 0)).toLocaleString('en-US')}</div>
          </div>
          <div className="brief-figure-copy">
            <p className="brief-label">{delta ? 'Sales, last 24 hours' : 'Rows in the workbook'}</p>
            <p className="brief-quiet">
              {delta ? (
                <>
                  <span className="mover up">+{added} added</span>
                  {' '}
                  <span className="mover down">−{removed} removed</span>
                </>
              ) : (
                'First snapshot. The 24-hour diff starts at the next read.'
              )}
            </p>
          </div>
          {delta ? <Movers delta={delta} /> : (
            <ul className="movers">
              {(status?.examples ?? []).slice(1, 7).map((row, i) => (
                <li key={i}>
                  <span>{moverName(row)}</span>
                  <span className="mono">{typeof row[3] === 'number' ? row[3].toLocaleString('en-US') : ''}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
      {decisions.length > 0 ? (
        <section className="decisions" aria-label="Needs a decision">
          <h2>Needs a decision</h2>
          <ul>
            {salesNeedsConnect ? (
              <li>
                <span>Connect a workbook</span>
                <Button tone="secondary" onClick={() => void pick()} disabled={busy}>Connect</Button>
              </li>
            ) : null}
            {calendarNeedsConnect ? (
              <li>
                <span>Connect your calendar</span>
                <Button tone="secondary" href={WALKTHROUGH}>Connect</Button>
              </li>
            ) : null}
            {researchNeedsAsk ? (
              <li>
                <span>Ask your first question</span>
                <Button tone="secondary" onClick={askFirst}>Ask</Button>
              </li>
            ) : null}
          </ul>
          {note ? <p className="alert" role="status">{note}</p> : null}
          {manualOpen ? (
            <div className="well">
              <input
                className="well-input"
                type="text"
                name="workbook-path"
                autoComplete="off"
                aria-label="Workbook path"
                placeholder="Full path to the workbook"
                value={pathInput}
                onChange={(e) => setPathInput(e.target.value)}
                onKeyDown={onPathKey}
              />
              <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void connect(pathInput.trim())}>
                Connect
              </button>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
