// The desk as a bento. Two columns that always close: on the left the
// pipeline hero and the moves table, on the right the decisions and the
// digest, each column's last cell taking the leftover height. Under
// them one row of plugin cells, three across; a remainder of one runs
// the full width, a remainder of two splits the row. On a phone the
// columns dissolve and every cell stacks in priority order.
//
// While the Sample data switch is on, a cell with no real source shows
// the sample world (sampleDesk.ts) and says so once, in its header.
import { useState, type ReactNode } from 'react';
import type { DashboardData, PluginCard } from '../types';
import Button from '../components/Button';
import { postJson } from '../api';
import TrackerCard from './TrackerCard';
import PluginCardView from './PluginCardView';
import { pluginKind, kindTag } from './pluginKind';
import { useWorkbookConnect } from './useWorkbookConnect';
import {
  MOVER_CAP,
  agentCheckedLine,
  decisionsEmptyText,
  deskCheckAlert,
  formatAmount,
  formatSigned,
  moversFromDelta,
  netByStage,
  netPipeline,
  recommendationRows,
} from './briefModel';
import {
  CellHead,
  DigestList,
  HealthMatrix,
  StageChart,
  TrackerFigure,
  WatchDiff,
  WireChart,
  WireState,
  clock,
  type HealthRow,
} from './cells';
import { SAMPLE_TRACKER, sampleDigest, sampleWatch } from './sampleDesk';

const WALKTHROUGH = '/walkthrough/calendar';
const SAMPLE_FILE = /(^|[\\/])sample[\\/]sample-[^\\/]+$/;

interface BriefProps {
  data: DashboardData;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

/** True when this plugin card is the workbook tracker, including its ~variant. */
function isTracker(card: PluginCard): boolean {
  return card.id === 'excel-report' || card.id.startsWith('excel-report~');
}

/** A clock time for an epoch-seconds stamp, or a hyphen when it is absent. */
function fromEpoch(ts: number | null | undefined): string {
  if (ts == null || !Number.isFinite(ts)) return '-';
  return clock(new Date(ts * 1000));
}

/**
 * A clock time for an ISO timestamp, or a hyphen when it is missing or unreadable.
 */
function fromIso(value: string | null | undefined): string {
  if (!value) return '-';
  const at = new Date(value);
  return Number.isNaN(at.getTime()) ? '-' : clock(at);
}

interface Lower {
  key: string;
  kind: string;
  node: ReactNode;
}

/** Grid spans for the lower row: three across, one left over full width, two split. */
function lowerSpans(count: number): number[] {
  const spans = Array.from({ length: count }, () => 4);
  const rest = count % 3;
  if (rest === 1) spans[count - 1] = 12;
  if (rest === 2) { spans[count - 1] = 6; spans[count - 2] = 6; }
  return spans;
}

/**
  * The dashboard's bento brief: the pipeline hero, the moves table, decisions, the
  * digest, then the plugin cells.
 *
  * A cell with no real source shows the sample world while the Sample data switch is
  * on. onRefetch reloads the dashboard once a source answers; onExpired hands a 401
  * back to the caller.
 */
export default function Brief({ data, onRefetch, onExpired }: BriefProps) {
  const [movesOpen, setMovesOpen] = useState(false);
  const [now] = useState(() => new Date());
  const workbook = useWorkbookConnect(onExpired, onRefetch);
  const { note, busy, manualOpen, pathInput, setPathInput, pick, connect, onPathKey } = workbook;

  const sample = Boolean(data.sample);
  const sales = data.sales;
  const status = sales.status;
  const configured = sales.mode === 'live' && Boolean(status?.configured);
  const salesIsSample = configured && SAMPLE_FILE.test(status?.path ?? '');
  const delta = status?.delta ?? null;
  const movers = delta ? moversFromDelta(delta) : [];
  const net = delta ? netPipeline(delta) : 0;
  const stages = netByStage(movers);
  const changedCount = movers.filter((mover) => mover.kind === 'changed').length;
  const addedCount = movers.filter((mover) => mover.kind === 'added').length;
  const removedCount = movers.filter((mover) => mover.kind === 'removed').length;
  // The layout is the truth the Customize panel saves: a plugin card the
  // layout does not list is hidden, and the layout's order is the order
  // the plugin cells render in. The server resolves every installed
  // plugin into the layout, so a card is missing from this list only
  // because the user hid it.
  const layoutOrder = new Map(data.layout.cards.map((card, index) => [card.key, index]));
  const pluginCards = data.plugins.cards
    .filter((card) => layoutOrder.has(card.id))
    .sort((a, b) => (layoutOrder.get(a.id) ?? 0) - (layoutOrder.get(b.id) ?? 0));
  const trackers = pluginCards.filter(isTracker);
  const salesNeedsConnect = trackers.length === 0 && sales.mode !== 'disabled'
    && (sales.mode === 'unconfigured' || status === null || !status.configured);
  const calendarNeedsConnect = data.commitments.mode !== 'live'
    || data.commitments.status?.state === 'empty'
    || data.commitments.status == null;
  // research.enabled is the same payload decision the server-rendered
  // card follows; a disabled source is asked to be turned on, not asked.
  const researchEnabled = data.research.enabled;
  const researchNeedsAsk = researchEnabled && data.research.lastAnsweredTs == null;

  /** Focus the command bar so the user can ask a first research question. */
  function askFirst() {
    document.querySelector<HTMLTextAreaElement>('.cmd-field')?.focus();
  }

  // ---- decisions ------------------------------------------------------
  // Setup decisions keep the desk usable before anything has been saved;
  // a waiting recommendation takes the cell over once the desk has one.
  const setupDecisions: Array<{ key: string; title: string; why: string; sample?: boolean; action: ReactNode }> = [];
  if (salesNeedsConnect) {
    setupDecisions.push({
      key: 'workbook',
      title: 'Connect a workbook',
      why: 'The pipeline figure and the moves come from it.',
      action: <Button tone="secondary" className="btn-sm" onClick={() => void pick()} disabled={busy}>Connect</Button>,
    });
  }
  if (calendarNeedsConnect) {
    setupDecisions.push({
      key: 'calendar',
      title: 'Connect your calendar',
      why: 'The digest reads today’s meetings from it.',
      action: <Button tone="secondary" className="btn-sm" href={WALKTHROUGH}>Connect</Button>,
    });
  }
  if (researchNeedsAsk) {
    setupDecisions.push({
      key: 'question',
      title: 'Ask your first question',
      why: 'Answers come from your company endpoint and are logged.',
      action: <Button tone="secondary" className="btn-sm" onClick={askFirst}>Ask</Button>,
    });
  }
  if (!researchEnabled) {
    setupDecisions.push({
      key: 'research-off',
      title: 'Turn research back on',
      why: 'Answers come from your company endpoint, and it is off in settings.',
      action: <Button tone="secondary" className="btn-sm" href="/settings">Open settings</Button>,
    });
  }
  const recommendations = recommendationRows(data);
  /** Dismiss one recommendation, then refresh the dashboard it was on. */
  async function dismissRecommendation(cardId: string) {
    const res = await postJson(`/inbox/cards/${cardId}/dismiss`);
    if (res.ok) await onRefetch();
  }
  const recommendationDecisions: typeof setupDecisions = recommendations.rows.map((row) => ({
    key: `rec-${row.key}`,
    title: row.title,
    why: row.why,
    sample: row.sample,
    action: (
      <>
        <Button tone="secondary" className="btn-sm" href={row.href}>{row.actionLabel}</Button>
        <Button tone="secondary" className="btn-sm" onClick={() => void dismissRecommendation(row.cardId)}>Not now</Button>
      </>
    ),
  }));
  const decisions = recommendationDecisions.length > 0 ? recommendationDecisions : setupDecisions;
  const decisionsEmpty = decisions.length === 0 ? decisionsEmptyText(data.agentLoop) : null;
  const decisionsMeta = recommendationDecisions.length > 0
    ? (recommendations.more > 0 ? <span className="mono">{recommendations.more} more in inbox</span> : undefined)
    : (decisions.length > 0 ? <span className="mono">{decisions.length} open</span> : undefined);
  const connected = data.sources.connected;
  const total = data.sources.total;

  // ---- digest ---------------------------------------------------------
  const event = data.commitments.status?.keyEvent;
  const digestItems = event
    ? [{ at: new Date(event.start), source: 'CAL' as const, title: event.subject, detail: [event.location, event.attendees ? `${event.attendees} people` : ''].filter(Boolean).join(', ') }]
    : sample ? sampleDigest(now) : [];
  const digestIsSample = !event && sample;

  // ---- desk health ----------------------------------------------------
  const commitments = data.commitments.status;
  /**
   * A source's status word from the dashboard payload, or "" when no source
   * carries that id.
   */
  const sourceStatus = (id: string) => data.sources.items.find((item) => item.id === id)?.status ?? '';
  const healthRows: HealthRow[] = [
    {
      name: 'Workbook',
      live: configured && status?.state !== 'unreadable' && status?.state !== 'locked',
      status: !configured ? 'off' : status?.state === 'healthy' || status?.state === 'first' ? 'live' : (status?.state ?? 'off').replace('_', ' '),
      lastRun: fromEpoch(status?.last_ok_ts ?? null),
      items: configured ? (status?.rowsSeen ?? 0).toLocaleString('en-US') : '-',
    },
    {
      name: 'Calendar',
      live: sourceStatus('calendar-bridge') === 'connected',
      status: sourceStatus('calendar-bridge') === 'connected' ? 'live' : 'off',
      lastRun: fromIso(commitments?.generatedAt ?? null),
      items: event ? '1' : '-',
    },
    {
      name: 'Research',
      live: researchEnabled && sourceStatus('research-endpoint') === 'connected',
      status: researchEnabled && sourceStatus('research-endpoint') === 'connected' ? 'live' : 'off',
      lastRun: fromEpoch(data.research.lastAnsweredTs),
      items: '-',
    },
    ...pluginCards.map((card) => ({
      name: card.title,
      live: card.freshness === 'fresh',
      status: card.freshness === 'fresh' ? 'live' : card.payload?.setup ? 'set up' : 'attention',
      lastRun: fromIso(card.checkedAt || null),
      items: card.payload?.setup ? '-' : String(card.payload?.elements?.length ?? 0),
    })),
  ];

  const LIST = new Intl.ListFormat('en-US', { style: 'long', type: 'conjunction' });
  /** The names as an English conjunction list, e.g. "A, B, and C". */
  const listJoin = (names: string[]) => LIST.format(names);

  // ---- the lower row ----------------------------------------------------
  const lower: Lower[] = [];
  lower.push({
    key: 'health',
    kind: 'health',
    node: (
      <>
        <CellHead tag="DESK HEALTH" meta={<span className="mono">{connected}/{total} live</span>} />
        <HealthMatrix rows={healthRows} />
        <p className="cell-foot health-foot">
          {(() => {
            const feeds = healthRows.slice(0, 3);
            const off = feeds.filter((row) => !row.live);
            const reading = healthRows.slice(3).filter((row) => row.live);
            if (off.length === 0) return 'Every source answered on its last run.';
            const base = `${listJoin(off.map((row) => row.name))} ${off.length === 1 ? 'is' : 'are'} not live yet.`;
            return reading.length > 0
              ? `${base} ${listJoin(reading.map((row) => row.name))} ${reading.length === 1 ? 'reads its own file' : 'read their own files'}.`
              : base;
          })()}
        </p>
        {(() => {
          const alert = deskCheckAlert(data.deskCheck);
          return alert ? (
            <p className="alert">
              <a href={alert.href}>{alert.label}</a>
            </p>
          ) : null;
        })()}
        {(() => {
          // The loop's quiet line (cell-foot is the muted tone): when the
          // supervised loop last checked the desk, shown once a pass has
          // run whatever the interval is set to now.
          const checked = agentCheckedLine(data.agentLoop);
          return checked ? <p className="cell-foot health-foot">{checked}</p> : null;
        })()}
      </>
    ),
  });
  if (trackers.length > 0) {
    for (const card of trackers) {
      lower.push({
        key: card.id,
        kind: 'tracker',
        node: (
          <>
            <CellHead tag="TRACKER" sample={Boolean(card.payload?.tracker?.sample)} />
            <TrackerCard card={card} onRefetch={onRefetch} onExpired={onExpired} />
          </>
        ),
      });
    }
  } else if (!data.plugins.cards.some(isTracker)) {
    // The placeholder asks for a first tracker, so it shows only when no
    // tracker exists at all: a hidden tracker card must not bring back
    // the setup nudge the user just put away.
    lower.push({
      key: 'tracker',
      kind: 'tracker',
      node: sample ? (
        <>
          <CellHead tag="TRACKER" sample />
          <TrackerFigure view={SAMPLE_TRACKER} />
        </>
      ) : (
        <>
          <CellHead tag="TRACKER" />
          <h3 className="cell-title">Workbook tracker</h3>
          <WireState
            line="Follow one number from any workbook: a total, a column, the rows you pick."
            action={<Button tone="secondary" className="btn-sm" href="/marketplace/plugin/excel-report">Add tracker</Button>}
          />
        </>
      ),
    });
  }
  const anyWatch = data.plugins.cards.some((card) => !isTracker(card) && pluginKind(card.id) === 'watch');
  if (!anyWatch) {
    lower.push({
      key: 'watch',
      kind: 'watch',
      node: sample ? (
        <>
          <CellHead tag="PAGE WATCH" sample />
          <WatchDiff view={sampleWatch(now)} />
        </>
      ) : (
        <>
          <CellHead tag="PAGE WATCH" />
          <h3 className="cell-title">Page watch</h3>
          <WireState
            shape="lines"
            line="No page is being watched. Name one page and see what changed on it."
            action={<Button tone="secondary" className="btn-sm" href="/marketplace/plugin/competitor-watch">Add a page</Button>}
          />
        </>
      ),
    });
  }
  for (const card of pluginCards.filter((c) => !isTracker(c))) {
    const kind = pluginKind(card.id);
    lower.push({
      key: card.id,
      kind,
      node: (
        <>
          <CellHead tag={kindTag(kind)} />
          <PluginCardView card={card} onRefetch={onRefetch} onExpired={onExpired} />
        </>
      ),
    });
  }
  const spans = lowerSpans(lower.length);

  // ---- render -----------------------------------------------------------
  const shown = movesOpen ? movers : movers.slice(0, MOVER_CAP);
  const maxMove = Math.max(1, ...movers.map((m) => Math.abs(m.delta)));

  return (
    <div className="brief">
      {data.update?.banner ? (
        <div className="alert" role="status">{data.update.banner}</div>
      ) : null}
      <div className="brief-col brief-main">
        <article className="cell cell-hero" aria-labelledby="cell-brief">
          <CellHead id="cell-brief" tag="PIPELINE" sample={salesIsSample} meta={configured && status?.path ? <span className="mono">{status.path.split(/[\\/]/).pop()}</span> : undefined} />
          {configured ? (
            <div className="hero-grid">
              <div className="hero-figure">
                <div className="kpi">
                  <div className={`value${delta && net < 0 ? ' down' : ''}${!delta || net === 0 ? ' flat' : ''}`}>
                    {delta ? formatSigned(net) : (status?.rowsSeen ?? 0).toLocaleString('en-US')}
                  </div>
                </div>
                <p className="brief-label">{delta ? 'Net pipeline, last 24 hours' : 'Rows in the workbook'}</p>
                {delta ? (
                  <dl className="hero-stats">
                    <div><dt>Changed</dt><dd>{changedCount}</dd></div>
                    <div><dt>Added</dt><dd>{addedCount}</dd></div>
                    <div><dt>Removed</dt><dd>{removedCount}</dd></div>
                  </dl>
                ) : (
                  <p className="brief-quiet">First snapshot. The 24-hour change starts at the next read.</p>
                )}
              </div>
              {delta && stages.length > 0 ? <StageChart stages={stages} /> : (
                <div className="stage-chart">
                  <p className="chart-cap">Net change by stage</p>
                  <WireChart bars={5} label="No change yet; the chart fills after the next read" />
                </div>
              )}
            </div>
          ) : (
            <div className="hero-grid">
              <div className="hero-figure">
                <div className="kpi"><div className="value flat ghost">-</div></div>
                <p className="brief-label">Net pipeline, last 24 hours</p>
                <p className="brief-quiet">No sales workbook is connected, so there is no pipeline figure yet.</p>
              </div>
              <div className="stage-chart">
                <p className="chart-cap">Net change by stage</p>
                <WireChart bars={5} />
              </div>
            </div>
          )}
        </article>
        <article className="cell cell-moves" aria-labelledby="cell-moves">
          <CellHead
            id="cell-moves"
            tag="MOVES"
            sample={salesIsSample && movers.length > 0}
            meta={movers.length > 0 ? <span className="mono">{shown.length} of {movers.length}</span> : undefined}
          />
          {delta && movers.length > 0 ? (
            <>
              <div className="table-scroll">
                <table className="moves">
                  <thead>
                    <tr>
                      <th scope="col">Deal</th>
                      <th scope="col">Stage</th>
                      <th scope="col" className="num">Close</th>
                      <th scope="col" className="num">Was → now</th>
                      <th scope="col" className="num">Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((mover, index) => (
                      <tr key={`${mover.name}-${index}`}>
                        <th scope="row">
                          <span className="deal">{mover.deal}</span>
                          {mover.previousName ? <span className="deal-was">was {mover.previousName}</span> : null}
                        </th>
                        <td className="stage-cell">{mover.stage || '-'}<span className="region mono">{mover.region}</span></td>
                        <td className="num mono">{mover.close || '-'}</td>
                        <td className="num mono was-now">
                          {mover.kind === 'changed' ? (
                            <>{formatAmount(mover.oldAmount)} <span aria-label="to">→</span> {formatAmount(mover.newAmount)}</>
                          ) : mover.kind === 'added' ? <span className="kind">new · {formatAmount(mover.newAmount)}</span>
                            : <span className="kind">left · {formatAmount(mover.oldAmount)}</span>}
                        </td>
                        <td className={mover.delta < 0 ? 'num mono change down' : 'num mono change up'}>
                          <span className="change-bar" aria-hidden="true">
                            <span style={{ width: `${(Math.abs(mover.delta) / maxMove) * 100}%` }} />
                          </span>
                          {formatSigned(mover.delta)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {movers.length > MOVER_CAP ? (
                <button type="button" className="text-btn" onClick={() => setMovesOpen((open) => !open)}>
                  {movesOpen ? `Show top ${MOVER_CAP}` : `See all ${movers.length}`}
                </button>
              ) : null}
            </>
          ) : (
            <>
              <div className="moves-wire" aria-hidden="true">
                <div className="mw-row mw-head"><span>Deal</span><span>Stage</span><span>Close</span><span>Was → now</span><span>Change</span></div>
                {[58, 72, 44, 66, 50].map((w, i) => (
                  <div className="mw-row" key={i}>
                    <i style={{ width: `${w}%` }} /><i style={{ width: '60%' }} /><i style={{ width: '50%' }} /><i style={{ width: '70%' }} /><i style={{ width: '45%' }} />
                  </div>
                ))}
              </div>
              <p className="cell-foot">{configured ? 'No deal has moved in the last 24 hours.' : 'Deals that move show here once a sales workbook is connected.'}</p>
            </>
          )}
        </article>
      </div>
      <div className="brief-col brief-side">
        {decisions.length > 0 || decisionsEmpty ? (
          <section className="cell cell-decisions" aria-label="Needs a decision">
            <CellHead tag="DECISIONS" meta={decisionsMeta} />
            <div className="setup-meter" role="img" aria-label={`${connected} of ${total} sources connected`}>
              {Array.from({ length: total }, (_, i) => <span key={i} className={i < connected ? 'on' : ''} />)}
              <span className="setup-meter-label mono">{connected}/{total} sources</span>
            </div>
            {decisions.length > 0 ? (
              <ul className="decisions">
                {decisions.map((d) => (
                  <li key={d.key}>
                    <div className="decision-text">
                      <span className="decision-title">{d.title}{d.sample ? <span className="sample-tag">SAMPLE DATA</span> : null}</span>
                      <span className="decision-why">{d.why}</span>
                    </div>
                    {d.action}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty">{decisionsEmpty}</p>
            )}
            {note ? <p className="alert" role="status">{note}</p> : null}
            {manualOpen ? (
              <div className="well">
                <input
                  className="well-input"
                  type="text"
                  name="workbook-path"
                  autoComplete="off"
                  aria-label="Workbook path"
                  placeholder="Full path to the workbook…"
                  value={pathInput}
                  onChange={(e) => setPathInput(e.target.value)}
                  onKeyDown={onPathKey}
                />
                <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => void connect(pathInput.trim())}>
                  Connect
                </button>
              </div>
            ) : null}
          </section>
        ) : null}
        <article className={digestItems.length > 0 ? 'cell cell-digest' : 'cell cell-digest is-empty'} aria-labelledby="cell-digest">
          <CellHead id="cell-digest" tag="DIGEST" sample={digestIsSample} meta={digestItems.length > 0 ? <span className="mono">{digestItems.length} items</span> : undefined} />
          {digestItems.length > 0 ? <DigestList items={digestItems} /> : (
            <div className="digest-empty">
              <p>Nothing on the calendar yet.</p>
              <Button tone="secondary" className="btn-sm" href={WALKTHROUGH}>Set up</Button>
            </div>
          )}
        </article>
      </div>
      {lower.map((cell, index) => (
        <article
          key={cell.key}
          className={`cell cell-${cell.kind} span-${spans[index]}${spans[index] === 12 ? ' is-wide' : ''}`}
        >
          {cell.node}
        </article>
      ))}
    </div>
  );
}