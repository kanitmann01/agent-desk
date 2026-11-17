// The morning brief: one figure, a list of movers, and one decision
// panel. It replaces the three equal cards on the dashboard. Customize
// mode still uses the cards, because reordering needs one object per card.
import { useState, type KeyboardEvent } from 'react';
import { postJson } from '../api';
import type { DashboardData } from '../types';
import Button from '../components/Button';
import TrackerCard from './TrackerCard';
import PluginCardView from './PluginCardView';
import { kindTag, pluginKind } from './pluginKind';
import {
  MOVER_CAP,
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

function Bars({ movers }: { movers: Mover[] }) {
  const rows = movers.slice(0, 6);
  const max = Math.max(...rows.map((mover) => Math.abs(mover.delta)), 1);
  if (rows.length === 0) return null;
  return (
    <div className="bars" role="img" aria-label="Largest deal changes">
      {rows.map((mover, index) => (
        <div className="bar-row" key={`${mover.name}-${index}`}>
          <span>{mover.name}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(Math.abs(mover.delta) / max) * 100}%` }} />
          </span>
        </div>
      ))}
    </div>
  );
}

export default function Brief({ data, onRefetch, onExpired }: BriefProps) {
  const [note, setNote] = useState('');
  const [manualOpen, setManualOpen] = useState(false);
  const [pathInput, setPathInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [movesOpen, setMovesOpen] = useState(false);

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

  const event = data.commitments.status?.keyEvent;
  const healthLabels: Record<string, string> = {
    'excel-watch': 'Workbook',
    'calendar-bridge': 'Calendar',
    'research-endpoint': 'Research',
  };
  const health = data.sources.items.length > 0
    ? data.sources.items.map((item) => ({
        id: healthLabels[item.id] ?? item.id,
        status: item.status.replaceAll('_', ' '),
        detail: item.detail,
      }))
    : [
        { id: 'Workbook', status: configured ? 'live' : 'not connected', detail: '' },
        { id: 'Calendar', status: calendarNeedsConnect ? 'not connected' : 'live', detail: '' },
        { id: 'Research', status: researchNeedsAsk ? 'waiting' : 'asked', detail: '' },
      ];
  const others = data.plugins.cards.filter((card) => !trackers.some((tracker) => tracker.id === card.id));

  return (
    <div className="brief">
      <article className="cell cell-hero span-8">
        <p className="tag">BRIEF</p>
        {configured ? (
          <>
            <div className="kpi">
              <div className={`value${delta && net < 0 ? ' down' : ''}${delta && net === 0 ? ' flat' : ''}`}>
                {delta ? formatSigned(net) : (status?.rowsSeen ?? 0).toLocaleString('en-US')}
              </div>
            </div>
            <p className="brief-label">{delta ? 'Net pipeline, last 24 hours' : 'Rows in the workbook'}</p>
            <p className="brief-quiet">
              {delta ? (
                <>
                  {changedCount > 0 ? <span>{changedCount} changed</span> : null}
                  {addedCount > 0 ? <span className="mover up">+{addedCount} added</span> : null}
                  {removedCount > 0 ? <span className="mover down">−{removedCount} removed</span> : null}
                </>
              ) : 'First snapshot. The 24-hour diff starts at the next read.'}
            </p>
            {delta ? <Bars movers={movers} /> : null}
          </>
        ) : (
          <div className="wire">
            <p>No workbook is connected, so there is no pipeline figure yet.</p>
          </div>
        )}
      </article>
      {decisions.length > 0 ? (
        <section className="cell cell-decisions span-4" aria-label="Needs a decision">
          <p className="tag">DECISIONS</p>
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
      <article className="cell cell-watch span-8">
        <p className="tag">TRACKING</p>
        {delta && movers.length > 0 ? (
          <>
            <table className="moves">
              <thead>
                <tr><th>Deal</th><th>Where</th><th>Change</th></tr>
              </thead>
              <tbody>
                {(movesOpen ? movers : movers.slice(0, MOVER_CAP)).map((mover, index) => (
                  <tr key={`${mover.name}-${index}`}>
                    <td>{moverTitle(mover)}</td>
                    <td className="mover-meta">{mover.meta}</td>
                    <td className={mover.delta < 0 ? 'mover down' : 'mover up'}>
                      {mover.kind === 'changed' && mover.oldAmount != null && mover.newAmount != null
                        ? `${formatAmount(mover.oldAmount)} → ${formatAmount(mover.newAmount)} `
                        : ''}
                      {formatSigned(mover.delta)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {movers.length > MOVER_CAP ? (
              <button type="button" className="brief-more" onClick={() => setMovesOpen((open) => !open)}>
                {movesOpen ? 'Show top 5' : 'See all'}
              </button>
            ) : null}
          </>
        ) : (
          <div className="wire"><p>No rows have moved in the last 24 hours.</p></div>
        )}
      </article>
      <article className="cell cell-digest span-4">
        <p className="tag">DIGEST</p>
        {event ? (
          <ul className="digest-list">
            <li>
              <span>{event.subject}</span>
              <time dateTime={event.start}>{event.start}</time>
            </li>
          </ul>
        ) : (
          <div className="wire">
            <p>Nothing is on the calendar yet.</p>
            <Button tone="secondary" href={WALKTHROUGH}>Set up</Button>
          </div>
        )}
      </article>
      <article className="cell cell-health span-4">
        <p className="tag">DESK</p>
        <ul className="matrix">
          {health.map((item) => (
            <li key={item.id}>
              <span>{item.id}</span>
              <span className="mono">{item.status}</span>
            </li>
          ))}
        </ul>
      </article>
      {trackers.map((card) => (
        <article className="cell cell-tracker span-5" key={card.id}>
          <p className="tag">TRACKING</p>
          <TrackerCard card={card} onRefetch={onRefetch} onExpired={onExpired} />
        </article>
      ))}
      {others.map((card) => {
        const kind = pluginKind(card.id);
        return (
          <article className={`cell cell-${kind} span-4`} key={card.id}>
            <p className="tag">{kindTag(kind)}</p>
            <PluginCardView card={card} onRefetch={onRefetch} onExpired={onExpired} />
          </article>
        );
      })}
    </div>
  );
}
