// The desk as a bento. Two columns that always close: on the left the
// pipeline hero and the moves table, on the right the decisions and the
// digest, each column's last cell taking the leftover height. Under
// them one row of plugin cells, three across; a remainder of one runs
// the full width, a remainder of two splits the row. On a phone the
// columns dissolve and every cell stacks in priority order.
//
// While the Sample data switch is on, a cell with no real source shows
// the sample world (sampleDesk.ts) and says so once, in its header.
import { useRef, useState, type ReactNode } from 'react';
import type { DashboardData, PluginCard } from '../types';
import Button from '../components/Button';
import { postJson } from '../api';
import { useBusy } from '../components/useBusy';
import TrackerCard from './TrackerCard';
import PluginCardView from './PluginCardView';
import SkillsCard from './SkillsCard';
import SetupStrip from './SetupStrip';
import { pluginKind, kindTag } from './pluginKind';
import { useWorkbookConnect } from './useWorkbookConnect';
import {
  MOVER_CAP,
  agentCheckedLine,
  decisionsEmptyText,
  deskActionLine,
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
  /** True when the Get started strip was hidden for this sitting. */
  setupDismissed?: boolean;
  /** Hide the Get started strip for this sitting. */
  onDismissSetup?: () => void;
  /** The saved ask whose run is in flight, so its row shows the wait. */
  skillBusyId?: number | null;
  /** Run a saved ask into the shared answer area. */
  onRunSkill?: (id: number) => void;
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
  // A cell whose content needs the whole row (the health matrix, a tracker
  // figure) takes 12 columns; the rest pair up.
  wide?: boolean;
}

/** Grid spans for the paired cells: pairs of 6, an odd last card full width. */
function lowerSpans(count: number): number[] {
  return Array.from({ length: count }, (_, index) =>
    (count % 2 === 1 && index === count - 1 ? 12 : 6));
}

/**
 * The dashboard's bento brief: the Get started strip while a step is open,
 * then the pipeline hero, the moves table, decisions, the digest and the
 * plugin cells.
 *
  * A cell with no real source shows the sample world while the Sample data switch is
  * on. onRefetch reloads the dashboard once a source answers; onExpired hands a 401
  * back to the caller.
 */
export default function Brief({
  data, onRefetch, onExpired, setupDismissed = false, onDismissSetup,
  skillBusyId = null, onRunSkill = () => {},
}: BriefProps) {
  const [movesOpen, setMovesOpen] = useState(false);
  const [now] = useState(() => new Date());
  // The workbook connect walk lives here because the strip's workbook step
  // and nothing else on this surface uses it.
  const workbook = useWorkbookConnect(onExpired, onRefetch);

  const sample = Boolean(data.sample);
  const sales = data.sales;
  const status = sales.status;
  const configured = sales.mode === 'live' && Boolean(status?.configured);
  const salesIsSample = configured && SAMPLE_FILE.test(status?.path ?? '');
  // A stale read keeps its last good delta on the wire; showing it as the
  // current pipeline move presents old numbers as today's. The card
  // already says it is stale, so drop the delta until the next good read.
  const delta = status?.state === 'stale' ? null : (status?.delta ?? null);
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
  // The payload lists visible cards only; a builtin absent from it is one
  // the reader hid, so its cells do not render.

  /** The layout's custom title for a card key, or null for its default name. */
  const layoutTitleFor = (key: string): string | null =>
    data.layout.cards.find((card) => card.key === key)?.title ?? null;

  /** True when the payload's visible layout lists this card key. */
  const shows = (key: string) => layoutOrder.has(key);
  const salesShown = shows('sales');
  const commitmentsShown = shows('commitments');
  const skillsShown = shows('skills') && data.skills.length > 0;
  const columnCount = (salesShown ? 1 : 0) + (commitmentsShown ? 1 : 0);
  const pluginCards = data.plugins.cards
    .filter((card) => layoutOrder.has(card.id))
    .sort((a, b) => (layoutOrder.get(a.id) ?? 0) - (layoutOrder.get(b.id) ?? 0));
  const trackers = pluginCards.filter(isTracker);
  /** The status word of one dashboard source, or an empty string. */
  const sourceStatus = (id: string) => data.sources.items.find((item) => item.id === id)?.status ?? '';
  // research.enabled is the same payload decision the server-rendered
  // card follows; a disabled source is asked to be turned on, not asked.
  const researchEnabled = data.research.enabled;
  const researchNeedsAsk = researchEnabled && data.research.lastAnsweredTs == null;
  // The AI is the one thing every model call needs, so the first question
  // waits for it. The step itself lives in the Get started strip.
  const aiConnected = sourceStatus('research-endpoint') === 'connected';
  // The desk's own action, named when it is new to this sitting (spec
  // 023): the poll watch sees the payload's agent-activity stamp move,
  // and this line says what the desk did, in the desk's own voice. The
  // sitting ref folds every stamp it has seen, so the line stands from
  // the first new pass until a newer one, and the pass the page opened
  // with is never announced.
  const sitting = useRef<{ baseline: number | null; newest: number | null } | null>(null);
  const rawStamp = data.agentLoop?.lastRunTs;
  const stamp = typeof rawStamp === 'number' && Number.isFinite(rawStamp) ? rawStamp : null;
  if (sitting.current === null) {
    sitting.current = { baseline: stamp, newest: stamp };
  } else if (stamp !== null && (sitting.current.newest === null || stamp > sitting.current.newest)) {
    sitting.current = { baseline: sitting.current.baseline, newest: stamp };
  }
  const deskAction = sitting.current === null
    ? null
    : deskActionLine(sitting.current.baseline, sitting.current.newest);
  // The Get started strip leads with the setup steps the server reports;
  // it goes away once every step is done, or for this sitting.
  const setupSteps = data.setup?.steps ?? [];
  const setupOpen = setupSteps.some((step) => !step.done);
  const showSetup = setupOpen && !setupDismissed;

  /** Focus the command bar so the user can ask a first research question. */
  function askFirst() {
    document.querySelector<HTMLTextAreaElement>('.cmd-field')?.focus();
  }

  // ---- decisions ------------------------------------------------------
  // The Get started strip owns the setup steps; this cell holds what needs
  // a yes or no, and a waiting recommendation takes it over once the desk
  // has one.
  const setupDecisions: Array<{ key: string; title: string; why: string; sample?: boolean; action: ReactNode }> = [];
  if (researchNeedsAsk && aiConnected) {
    setupDecisions.push({
      key: 'question',
      title: 'Ask your first question',
      why: 'Answers come from your AI and are logged.',
      action: <Button tone="secondary" className="btn-sm" onClick={askFirst}>Ask</Button>,
    });
  }
  if (!researchEnabled) {
    setupDecisions.push({
      key: 'research-off',
      title: 'Turn research back on',
      why: 'Answers come from your AI, and it is turned off in settings.',
      action: <Button tone="secondary" className="btn-sm" href="/settings">Open settings</Button>,
    });
  }
  const recommendations = recommendationRows(data);
  const [dismissing, setDismissing] = useState<string | null>(null);
  const [dismissError, setDismissError] = useState<{ cardId: string; text: string } | null>(null);
  // The row that started the dismiss shows it after 100 ms; every other
  // row refuses a second press until it settles.
  const dismissShown = useBusy(dismissing !== null);
  /** Dismiss one recommendation, then refresh the dashboard it was on. */
  async function dismissRecommendation(cardId: string) {
    setDismissing(cardId);
    setDismissError(null);
    try {
      const res = await postJson(`/inbox/cards/${cardId}/dismiss`);
      if (!res.ok) {
        setDismissError({ cardId, text: 'Could not dismiss that decision. Try again.' });
        return;
      }
      await onRefetch();
    } catch {
      setDismissError({
        cardId,
        text: 'Could not reach the desk. Check the connection and try again.',
      });
    } finally {
      setDismissing(null);
    }
  }
  const recommendationDecisions: typeof setupDecisions = recommendations.rows.map((row) => ({
    key: `rec-${row.key}`,
    title: row.title,
    why: row.why,
    sample: row.sample,
    action: (
      <>
        <Button tone="secondary" className="btn-sm" href={row.href}>{row.actionLabel}</Button>
        <Button
          tone="secondary"
          className="btn-sm"
          disabled={dismissing !== null}
          pending={dismissShown && dismissing === row.cardId}
          pendingLabel="Dismissing..."
          onClick={() => void dismissRecommendation(row.cardId)}
        >
          Not now
        </Button>
        {dismissError?.cardId === row.cardId ? (
          <span className="alert decision-error" role="alert">{dismissError.text}</span>
        ) : null}
      </>
    ),
  }));
  const decisions = recommendationDecisions.length > 0 ? recommendationDecisions : setupDecisions;
  const decisionsEmpty = decisions.length === 0 ? decisionsEmptyText(data.agentLoop) : null;
  const decisionsMeta = recommendationDecisions.length > 0
    ? (recommendations.more > 0 ? <a className="mono" href="/inbox">{recommendations.more} more in inbox</a> : undefined)
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
  // A source wired to the sample set is reported as "sample" by the
  // server: it is showing something, and it is not live.
  const workbookSample = sourceStatus('excel-watch') === 'sample';
  const calendarSource = sourceStatus('calendar-bridge');
  /**
   * Desk health: the three desk sources, then the plugin rows as their own
   * group. The source counter counts exactly the rows above it.
   */
  const sourceRows: HealthRow[] = [
    {
      name: 'Workbook',
      live: configured && !workbookSample && status?.state !== 'unreadable' && status?.state !== 'locked',
      status: workbookSample && configured ? 'sample'
        : !configured ? 'off' : status?.state === 'healthy' || status?.state === 'first' ? 'live' : (status?.state ?? 'off').replace('_', ' '),
      lastRun: fromEpoch(status?.last_ok_ts ?? null),
      items: configured ? (status?.rowsSeen ?? 0).toLocaleString('en-US') : '-',
    },
    {
      name: 'Calendar',
      live: calendarSource === 'connected',
      status: calendarSource === 'connected' ? 'live' : calendarSource === 'sample' ? 'sample' : 'off',
      lastRun: fromIso(commitments?.generatedAt ?? null),
      items: event ? '1' : '-',
    },
    {
      name: 'AI',
      live: researchEnabled && sourceStatus('research-endpoint') === 'connected',
      status: researchEnabled && sourceStatus('research-endpoint') === 'connected' ? 'live' : 'off',
      lastRun: fromEpoch(data.research.lastAnsweredTs),
      items: '-',
    },
  ];
  const pluginRows: HealthRow[] = pluginCards.map((card) => ({
    name: card.title,
    live: card.freshness === 'fresh',
    status: card.freshness === 'fresh' ? 'live' : card.payload?.setup ? 'set up' : 'attention',
    // A card that never ran has no checkedAt: say never, not the clock.
    lastRun: card.checkedAt ? fromIso(card.checkedAt) : 'never',
    items: card.payload?.setup ? '-' : String(card.payload?.elements?.length ?? 0),
  }));
  const sourceLive = sourceRows.filter((row) => row.live).length;

  const LIST = new Intl.ListFormat('en-US', { style: 'long', type: 'conjunction' });
  /** The names as an English conjunction list, e.g. "A, B, and C". */
  const listJoin = (names: string[]) => LIST.format(names);

  // ---- the lower row ----------------------------------------------------
  const lower: Lower[] = [];
  lower.push({
    key: 'health',
    kind: 'health',
    wide: true,
    node: (
      <>
        <CellHead tag="DESK HEALTH" meta={<span className="mono">{sourceLive} of {sourceRows.length} sources live</span>} />
        <HealthMatrix sources={sourceRows} plugins={pluginRows} />
        <p className="cell-foot health-foot">
          {(() => {
            const off = sourceRows.filter((row) => !row.live);
            const reading = pluginRows.filter((row) => row.live);
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
        {deskAction ? (
          // Announced politely: the line arrives on its own, while the
          // user reads, so it is a status and not a surprise.
          <p className="cell-foot health-foot" role="status">{deskAction}</p>
        ) : null}
      </>
    ),
  });
  if (trackers.length > 0) {
    for (const card of trackers) {
      lower.push({
        key: card.id,
        kind: 'tracker',
        wide: true,
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
            action={data.deskNetwork === false
              ? <p className="w-note">This desk cannot read web pages yet</p>
              : <Button tone="secondary" className="btn-sm" href="/marketplace/plugin/competitor-watch">Add a page</Button>}
          />
        </>
      ),
    });
  }
  // The saved asks ride in the lower row as a builtin cell, ordered with
  // the plugin cells by the layout the Customize panel saved.
  const lowerCards: Array<{ key: string; kind: string; order: number; node: ReactNode }> = [];
  if (skillsShown) {
    lowerCards.push({
      key: 'skills',
      kind: 'skills',
      order: layoutOrder.get('skills') ?? 0,
      node: (
        <>
          <CellHead
            tag="SKILLS"
            meta={<span className="mono">{data.skills.length} saved</span>}
          />
          <SkillsCard
            skills={data.skills}
            title={layoutTitleFor('skills') ?? undefined}
            busy={skillBusyId !== null}
            busyId={skillBusyId}
            onRun={onRunSkill}
          />
        </>
      ),
    });
  }
  for (const card of pluginCards.filter((c) => !isTracker(c))) {
    const kind = pluginKind(card.id);
    lowerCards.push({
      key: card.id,
      kind,
      order: layoutOrder.get(card.id) ?? 0,
      node: (
        <>
          <CellHead tag={kindTag(kind)} />
          <PluginCardView card={card} onRefetch={onRefetch} onExpired={onExpired} />
        </>
      ),
    });
  }
  lowerCards.sort((a, b) => a.order - b.order);
  for (const cell of lowerCards) {
    lower.push({ key: cell.key, kind: cell.kind, node: cell.node });
  }
  // The health row and every tracker take the full width; the rest pair up.
  const narrow = lower.filter((cell) => !cell.wide);
  const narrowSpans = lowerSpans(narrow.length);
  let narrowIndex = 0;
  const spans = lower.map((cell) => (cell.wide ? 12 : narrowSpans[narrowIndex++]));

  const shown = movesOpen ? movers : movers.slice(0, MOVER_CAP);
  const maxMove = Math.max(1, ...movers.map((m) => Math.abs(m.delta)));

  // Sales owns the pipeline and moves cells; commitments owns the
  // decisions and digest cells. A hidden card drops its column; the
  // column whose card comes first in the saved layout comes first in
  // the flow, so moving a card changes where its cells sit. A column
  // left alone takes the full row.
  /** A card column's class, full-width when its hidden partner left it alone. */
  const columnClass = (name: string) =>
    `brief-col ${name}${columnCount === 1 ? ' brief-solo' : ''}`;
  const mainColumn = salesShown ? (
    <div className={columnClass('brief-main')} key="sales">
        <article className="cell cell-hero" aria-labelledby="cell-brief">
          <CellHead id="cell-brief" tag="PIPELINE" label={layoutTitleFor('sales')} sample={salesIsSample} meta={configured && status?.path ? <span className="mono">{status.path.split(/[\\/]/).pop()}</span> : undefined} />
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
                    {[
                      { label: 'Changed', count: changedCount },
                      { label: 'Added', count: addedCount },
                      { label: 'Removed', count: removedCount },
                    ].map((stat) => (
                      <div key={stat.label}>
                        <dt>{stat.label}</dt>
                        <dd title={`${stat.label}: ${stat.count.toLocaleString('en-US')}`}>
                          {stat.count.toLocaleString('en-US')}
                        </dd>
                      </div>
                    ))}
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
            label={layoutTitleFor('sales')}
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
  ) : null;
  const sideColumn = commitmentsShown ? (
    <div className={columnClass('brief-side')} key="commitments">
        {decisions.length > 0 || decisionsEmpty ? (
          <section className="cell cell-decisions" aria-label="Needs a decision">
            <CellHead tag="DECISIONS" label={layoutTitleFor('commitments')} meta={decisionsMeta} />
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
                    <span className="decision-actions">{d.action}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty">{decisionsEmpty}</p>
            )}
          </section>
        ) : null}
        <article className={digestItems.length > 0 ? 'cell cell-digest' : 'cell cell-digest is-empty'} aria-labelledby="cell-digest">
          <CellHead id="cell-digest" tag="DIGEST" label={layoutTitleFor('commitments')} sample={digestIsSample} meta={digestItems.length > 0 ? <span className="mono">{digestItems.length} items</span> : undefined} />
          {digestItems.length > 0 ? <DigestList items={digestItems} /> : (
            <div className="digest-empty">
              <p>Nothing on the calendar yet.</p>
              {/* The Get started strip asks for the calendar one row above;
                  the cell keeps its own way in only while the strip is out
                  of the way. */}
              {!showSetup ? (
                <Button tone="secondary" className="btn-sm" href={WALKTHROUGH}>Set up</Button>
              ) : null}
            </div>
          )}
        </article>
      </div>
  ) : null;
  const columns = [
    { key: 'sales', index: layoutOrder.get('sales') ?? 0, node: mainColumn },
    { key: 'commitments', index: layoutOrder.get('commitments') ?? 0, node: sideColumn },
  ].filter((column) => column.node !== null).sort((a, b) => a.index - b.index);

  // ---- render -----------------------------------------------------------

  return (
    <div className="brief">
      {data.update?.banner ? (
        <div className="alert" role="status">{data.update.banner}</div>
      ) : null}
      {showSetup && data.setup ? (
        <SetupStrip
          setup={data.setup}
          onDismiss={() => onDismissSetup?.()}
          onRefetch={onRefetch}
          onExpired={onExpired}
          workbook={workbook}
        />
      ) : null}
      {columns.map((column) => column.node)}
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