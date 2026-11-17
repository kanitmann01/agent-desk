// The morning brief: one figure, a list of movers, and one decision
// panel. It replaces the three equal cards on the dashboard. Customize
// mode still uses the cards, because reordering needs one object per card.
import { useState, type KeyboardEvent } from 'react';
import { postJson } from '../api';
import type { DashboardData } from '../types';
import Button from '../components/Button';
import TrackerCard from './TrackerCard';
import {
  MOVER_CAP,
  dealMeta,
  dealName,
  formatAmount,
  formatSigned,
  moversFromDelta,
  netPipeline,
  type Mover,
} from './briefModel';

const WALKTHROUGH = '/walkthrough/calendar';

interface BriefProps {
  data: DashboardData;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

function moverTitle(mover: Mover): string {
  if (mover.previousName) return `${mover.previousName} → ${mover.name}`;
  return mover.name;
}

function moverPath(mover: Mover): string {
  if (mover.kind === 'changed' && mover.oldAmount != null && mover.newAmount != null) {
    return `${formatAmount(mover.oldAmount)} → ${formatAmount(mover.newAmount)}`;
  }
  if (mover.kind === 'added') return 'Added';
  if (mover.kind === 'removed') return 'Removed';
  return '';
}

function Movers({ movers }: { movers: Mover[] }) {
  const [open, setOpen] = useState(false);
  if (movers.length === 0) {
    return <p className="brief-quiet">No rows changed in the last 24 hours.</p>;
  }
  const shown = open ? movers : movers.slice(0, MOVER_CAP);
  const hidden = movers.length - MOVER_CAP;
  return (
    <>
      <ul className="movers">
        {shown.map((mover, index) => (
          <li key={`${mover.kind}-${index}-${mover.name}`}>
            <span className="mover-name">{moverTitle(mover)}</span>
            <span className={mover.delta < 0 ? 'mover down' : 'mover up'}>{formatSigned(mover.delta)}</span>
            {mover.meta ? <span className="mover-meta">{mover.meta}</span> : <span />}
            <span className="mover-path">{moverPath(mover)}</span>
          </li>
        ))}
      </ul>
      {hidden > 0 ? (
        <button type="button" className="brief-more" onClick={() => setOpen((value) => !value)}>
          {open ? 'Show top 5' : 'See all'}
        </button>
      ) : null}
    </>
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
  const movers = delta ? moversFromDelta(delta) : [];
  const net = delta ? netPipeline(delta) : 0;
  const changedCount = movers.filter((mover) => mover.kind === 'changed').length;
  const addedCount = movers.filter((mover) => mover.kind === 'added').length;
  const removedCount = movers.filter((mover) => mover.kind === 'removed').length;
  const trackers = data.plugins.cards.filter((card) => (
    card.id === 'excel-report' || card.id.startsWith('excel-report~')
  ));
  const salesNeedsConnect = trackers.length === 0 && sales.mode !== 'disabled'
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
      {trackers.length > 0 ? (
        <div className="tracker-stack">
          {trackers.map((card) => (
            <TrackerCard key={card.id} card={card} onRefetch={onRefetch} onExpired={onExpired} />
          ))}
        </div>
      ) : configured ? (
        <div className="brief-figure">
          <div className="kpi">
            <div className={`value${delta && net < 0 ? ' down' : ''}${delta && net === 0 ? ' flat' : ''}`}>
              {delta ? formatSigned(net) : (status?.rowsSeen ?? 0).toLocaleString('en-US')}
            </div>
          </div>
          <div className="brief-figure-copy">
            <p className="brief-label">{delta ? 'Net pipeline, last 24 hours' : 'Rows in the workbook'}</p>
            <p className="brief-quiet">
              {delta ? (
                <>
                  {changedCount > 0 ? <span>{changedCount} changed</span> : null}
                  {addedCount > 0 ? <span className="mover up">+{addedCount} added</span> : null}
                  {removedCount > 0 ? <span className="mover down">−{removedCount} removed</span> : null}
                </>
              ) : (
                'First snapshot. The 24-hour diff starts at the next read.'
              )}
            </p>
          </div>
          {delta ? <Movers movers={movers} /> : (
            <ul className="movers">
              {(status?.examples ?? []).slice(1, 1 + MOVER_CAP).map((row, i) => {
                const cells = row as unknown[];
                const amount = cells[3];
                return (
                  <li key={i}>
                    <span className="mover-name">{dealName(cells)}</span>
                    <span className="mono">{typeof amount === 'number' ? formatAmount(amount) : ''}</span>
                    {dealMeta(cells) ? <span className="mover-meta">{dealMeta(cells)}</span> : <span />}
                    <span />
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : (
        <p className="brief-lead">Connect a workbook and this desk shows the pipeline change and the deals that moved.</p>
      )}
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
