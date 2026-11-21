// The bento cell parts. Each cell kind draws its own data miniature, so
// no two kinds read alike: the hero's stage chart, the decisions'
// setup meter, the moves table's magnitude bars, the digest's timeline,
// the desk-health matrix, the tracker's sparkline and pace bar, the
// page watch's diff, and the dotted wireframe of a plugin that is not
// set up yet.
import type { ReactNode } from 'react';
import type { TrackerView } from '../types';
import type { StageNet } from './briefModel';
import { formatCompact, formatSigned } from './briefModel';
import type { DigestItem, WatchView } from './sampleDesk';

const TIME = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

/** A local clock time in 24-hour "HH:MM", in the browser's locale. */
export function clock(at: Date): string {
  return TIME.format(at);
}

/**
 * A cell's header line: the tag as the cell's heading, an optional meta set to
 * its right, and the sample-data tag once the cell is showing sample data.
 */
export function CellHead({ tag, sample = false, meta, id }: {
  tag: string;
  sample?: boolean;
  meta?: ReactNode;
  id?: string;
}) {
  return (
    <header className="cell-head">
      <h2 className="tag" id={id}>{tag}</h2>
      {meta != null ? <span className="cell-meta">{meta}</span> : null}
      {sample ? <span className="sample-tag">SAMPLE DATA</span> : null}
    </header>
  );
}

const STAGE_ORDER = ['Prospect', 'Qualify', 'Propose', 'Negotiate', 'Closed Won', 'Closed Lost'];

/**
 * A stage's place in pipeline order; a stage the order does not know sorts
 * after every known one.
 */
function stageRank(stage: string): number {
  const index = STAGE_ORDER.indexOf(stage);
  return index < 0 ? STAGE_ORDER.length : index;
}

/** Net change per stage as diverging columns on one zero line. */
export function StageChart({ stages }: { stages: StageNet[] }) {
  const ordered = [...stages].sort((a, b) => stageRank(a.stage) - stageRank(b.stage));
  const up = Math.max(0, ...ordered.map((s) => s.net));
  const down = Math.max(0, ...ordered.map((s) => -s.net));
  const span = up + down || 1;
  const zero = (up / span) * 100;
  const label = ordered.map((s) => `${s.stage} ${formatSigned(s.net)}`).join(', ');
  return (
    <figure className="stage-chart" aria-label={`Net change by stage: ${label}`}>
      <figcaption className="chart-cap">Net change by stage</figcaption>
      <div className="stage-plot" style={{ ['--z' as string]: String(zero / 100) }}>
        <span className="stage-zero" aria-hidden="true" />
        {ordered.map((s) => {
          const height = (Math.abs(s.net) / span) * 100;
          const isUp = s.net >= 0;
          return (
            <div className="stage-col" key={s.stage} aria-hidden="true">
              <span
                className={isUp ? 'stage-bar up' : 'stage-bar down'}
                style={isUp
                  ? { bottom: `${100 - zero}%`, height: `${height}%` }
                  : { top: `${zero}%`, height: `${height}%` }}
              />
              <span
                className={isUp ? 'stage-val up' : 'stage-val down'}
                style={isUp
                  ? { bottom: `calc(${100 - zero + height}% + 4px)` }
                  : { top: `calc(${zero + height}% + 4px)` }}
              >
                {s.net > 0 ? '+' : s.net < 0 ? '−' : ''}{formatCompact(Math.abs(s.net))}
              </span>
            </div>
          );
        })}
      </div>
      <div className="stage-axis" aria-hidden="true">
        {ordered.map((s) => (
          <span key={s.stage}>
            {s.stage}
            <small>{s.deals} {s.deals === 1 ? 'deal' : 'deals'}</small>
          </span>
        ))}
      </div>
    </figure>
  );
}

/** A dotted chart skeleton for a figure that has no history yet. */
export function WireChart({ bars = 6, label }: { bars?: number; label?: string }) {
  const heights = [38, 62, 46, 80, 54, 70, 44, 66].slice(0, bars);
  return (
    <div className="wire-chart" aria-hidden={label ? undefined : true} aria-label={label} role={label ? 'img' : undefined}>
      {heights.map((h, i) => <span key={i} style={{ height: `${h}%` }} />)}
    </div>
  );
}

/**
 * A trend line over the readings, scaled to their own range and marked at the
 * last point.
 *
 * Two readings are needed: the horizontal scale divides by one less than the
 * count, so a single point has no place to sit.
 */
export function Sparkline({ points, label }: { points: number[]; label: string }) {
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const xy = points.map((point, index) => ({
    x: (index / (points.length - 1)) * 200,
    y: 44 - ((point - min) / span) * 40,
  }));
  const line = xy.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const last = xy[xy.length - 1];
  return (
    <div className="spark">
      <svg viewBox="-4 0 208 48" preserveAspectRatio="none" role="img" aria-label={label}>
        <line x1="0" x2="200" y1="44" y2="44" className="spark-base" />
        <polyline points={line} className="spark-line" vectorEffect="non-scaling-stroke" />
        <circle cx={last.x} cy={last.y} r="3" className="spark-end" />
      </svg>
      <div className="spark-scale" aria-hidden="true">
        <span>{formatCompact(max)}</span>
        <span>{formatCompact(min)}</span>
      </div>
    </div>
  );
}

/** "read 2 min ago" for a reading timestamp, second precision. */
export function readAgo(at: number): string {
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - at));
  if (seconds < 45) return 'just now';
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

/**
 * A displayed figure as a number, or null when nothing numeric is in it.
 *
 * Every character but digits, a decimal point and a minus sign is stripped
 * first, so a currency symbol, a thousands separator or a unit suffix parses.
 */
function parseFigure(value: string): number | null {
  const n = Number(value.replace(/[^0-9.-]/g, ''));
  return Number.isFinite(n) && value.trim() !== '' ? n : null;
}

/** The tracker pattern: name, big figure, signed delta, trend, pace. */
export function TrackerFigure({ view, action }: { view: TrackerView; action?: ReactNode }) {
  const goal = view.goal ? parseFigure(view.goal.value) : null;
  const now = parseFigure(view.value);
  const pace = goal && now != null ? Math.max(0, Math.min(1, now / goal)) : null;
  const deltaClass = view.direction === 'down' ? 'delta-chip down' : view.direction === 'up' ? 'delta-chip up' : 'delta-chip';
  return (
    <div className="tracker">
      <div className="tracker-title">
        <h3>{view.name}</h3>
        {action}
      </div>
      <div className="tracker-figure">
        <span className="figure">{view.value}</span>
        {view.unit ? <span className="figure-unit">{view.unit}</span> : null}
      </div>
      <p className="tracker-delta">
        <span className={deltaClass}>{view.delta === 'First reading' ? 'First reading' : view.delta}</span>
        {view.delta === 'First reading' ? null : <span>since the last reading</span>}
      </p>
      {view.points.length >= 2 ? <Sparkline points={view.points} label={`${view.points.length} readings`} /> : <WireChart bars={8} />}
      {pace != null && view.goal ? (
        <div className="pace">
          <div className="pace-track" aria-hidden="true">
            <span style={{ width: `${pace * 100}%` }} />
          </div>
          <p className="pace-note">
            <span className="mono">{Math.round(pace * 100)}%</span> of {view.goal.value}{view.goal.unit ? ` ${view.goal.unit}` : ''}
            {view.paceNote ? <span className="pace-extra">{view.paceNote}</span> : null}
          </p>
        </div>
      ) : view.paceNote ? <p className="pace-note">{view.paceNote}</p> : null}
      <p className="cell-foot mono">
        {view.file}
        {typeof view.rowsSeen === 'number' ? ` · ${view.rowsSeen.toLocaleString('en-US')} rows` : ''}
        {view.readAt ? ` · read ${readAgo(view.readAt)}` : ''}
      </p>
    </div>
  );
}

/**
 * A digest as a timeline: each item's local time, source, title and detail, in
 * the order given.
 */
export function DigestList({ items }: { items: DigestItem[] }) {
  return (
    <ol className="digest">
      {items.map((item, index) => (
        <li key={index}>
          <time className="digest-time" dateTime={item.at.toISOString()}>{clock(item.at)}</time>
          <span className="digest-src">{item.source}</span>
          <span className="digest-text">
            <span className="digest-title" title={item.title}>{item.title}</span>
            <span className="digest-detail" title={item.detail || undefined}>{item.detail}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

/**
 * A watched page's latest diff, plus one bar per day of the last seven.
 *
 * Removed lines are struck through and added lines underlined; a day with no
 * changes still draws a short stub, so the week reads as seven days.
 */
export function WatchDiff({ view }: { view: WatchView }) {
  const max = Math.max(1, ...view.history);
  return (
    <div className="watch">
      <div className="watch-title">
        <h3>{view.name}</h3>
        <span className="watch-url mono" title={view.url}>{view.url}</span>
      </div>
      <div className="diff" role="group" aria-label={`${view.changes} changes since the last check`}>
        {view.lines.map((line, index) => (
          <p key={index} className={`diff-line ${line.kind}`}>
            <span className="diff-mark" aria-hidden="true">{line.kind === 'added' ? '+' : line.kind === 'removed' ? '−' : ' '}</span>
            {line.kind === 'removed' ? <del>{line.text}</del> : line.kind === 'added' ? <ins>{line.text}</ins> : <span>{line.text}</span>}
          </p>
        ))}
      </div>
      <div className="watch-foot">
        <div className="watch-week-wrap">
          <div className="watch-week" aria-label={`Changes per day, last 7 days: ${view.history.join(', ')}`} role="img">
            {view.history.map((n, i) => (
              <span key={i} className={n > 0 ? 'on' : ''} style={{ height: `${Math.max(8, (n / max) * 100)}%` }} />
            ))}
          </div>
          <span className="watch-week-label" aria-hidden="true">7 days</span>
        </div>
        <p className="cell-foot mono">checked {clock(view.checkedAt)} · {view.changes} changes</p>
      </div>
    </div>
  );
}

export interface HealthRow {
  name: string;
  live: boolean;
  status: string;
  lastRun: string;
  items: string;
}

/**
 * Desk health as one row per source: a live dot, its status word, the last run
 * time and the item count.
 *
 * Every cell arrives as display text: the table formats nothing, so a value
 * shows exactly as given.
 */
export function HealthMatrix({ rows }: { rows: HealthRow[] }) {
  return (
    <table className="matrix">
      <thead>
        <tr>
          <th scope="col">Source</th>
          <th scope="col">Status</th>
          <th scope="col" className="num">Last run</th>
          <th scope="col" className="num">Items</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.name}>
            <th scope="row" title={row.name}>{row.name}</th>
            <td>
              <span className={row.live ? 'sq on' : 'sq'} aria-hidden="true" />
              {row.status}
            </td>
            <td className="num mono">{row.lastRun}</td>
            <td className="num mono">{row.items}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** A plugin that is installed or offered but not set up: a dotted
 *  wireframe of what it will draw, one line, one action. */
export function WireState({ line, action, shape = 'bars', wide = false }: {
  line: string;
  action: ReactNode;
  shape?: 'bars' | 'lines' | 'rows';
  wide?: boolean;
}) {
  return (
    <div className={wide ? 'wire wire-wide' : 'wire'}>
      {shape === 'bars' ? <WireChart /> : (
        <div className={`wire-${shape}`} aria-hidden="true">
          {[72, 54, 88, 40].map((w, i) => <span key={i} style={{ width: `${w}%` }} />)}
        </div>
      )}
      <div className="wire-copy">
        <p>{line}</p>
        {action}
      </div>
    </div>
  );
}
