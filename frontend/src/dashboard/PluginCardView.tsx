// One installed plugin's dashboard card, rendered from the payload's
// plugin data (never server HTML). Fresh with a bound payload: the
// host-computed metrics and notes the ui-schema asked for. Fresh
// without one: the version and what it is reading. Attention: the
// cause and the honest note about Re-test, amber. The overflow menu
// re-tests the plugin's data source through the plugin endpoint and
// links the plugins page; the item refuses clicks while one is running.
import { Fragment, useState } from 'react';
import { postJson, pressReading, type PressBody } from '../api';
import type {
  InsightAnswer,
  InsightBlock,
  InsightPress,
  InsightWhyItem,
  PluginCard,
  PluginChecklistItem,
  PluginElement,
  PluginListRow,
  PluginTimelineItem,
} from '../types';
import { knownKind } from '../plugins/vocabulary';
import WidgetCard, { type CardMenuItem } from '../components/WidgetCard';
import TrackerCard from './TrackerCard';
import Button from '../components/Button';
import { PhaseLine, usePhase } from '../components/feedback';
import { useBusy } from '../components/useBusy';
import { staleSince } from '../fmt';
import { useFaceActions } from '../face/FaceProvider';
import { useFaceActivity } from '../face/useFaceActivity';
import { WireState } from './cells';
import { PendingBody } from './pending';

interface PluginCardViewProps {
  card: PluginCard;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

/**
 * Draw one element inside a wrapper carrying its kind: metric, text, delta,
 * progress, list, table, sparkline, status, timeline or checklist.
 *
 * A reason on the element prints as the note beneath the value; a kind this
 * view does not know falls back to its text. The data attribute is the hook a
 * test uses to prove every vocabulary kind reaches the SPA, and it gives one
 * element a stable styling boundary.
 */
export function ElementView({ element }: { element: PluginElement }) {
  return (
    <div className="w-element" data-element-kind={element.kind}>
      <ElementBody element={element} />
    </div>
  );
}

/** Draw one element's body; ElementView owns the kind wrapper. */
function ElementBody({ element }: { element: PluginElement }) {
  const blank = element.reason ? <p className="w-note">{element.reason}</p> : null;
  if (element.kind === 'metric') {
    return (
      <>
        <p className="w-big">{element.value ?? ''}</p>
        {element.label ? <p className="w-note">{element.label}</p> : null}
        {blank}
      </>
    );
  }
  if (element.kind === 'text') {
    return (
      <>
        {element.label ? <p className="w-list-title">{element.label}</p> : null}
        <p className="w-note">{element.text ?? ''}</p>
        {blank}
      </>
    );
  }
  if (element.kind === 'delta') {
    return (
      <p className="w-note">
        {element.label ? `${element.label}: ` : ''}{element.value ?? ''} {element.direction ?? ''}
      </p>
    );
  }
  if (element.kind === 'progress') {
    const value = typeof element.value === 'number' ? element.value : 0;
    const target = typeof element.target === 'number' && element.target > 0 ? element.target : 0;
    const pct = target > 0 ? Math.max(0, Math.min(100, (value / target) * 100)) : 0;
    return (
      <>
        {element.label ? <p className="w-list-title">{element.label}</p> : null}
        <div className="w-progress" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
          <span style={{ width: `${pct}%` }} />
        </div>
        <p className="w-note">{target > 0 ? `${value} of ${target}${element.unit ? ` ${element.unit}` : ''}` : 'No target reported.'}</p>
        {blank}
      </>
    );
  }
  if (element.kind === 'list') {
    const rows = (element.rows ?? []) as PluginListRow[];
    if (!rows.length) return blank;
    return (
      <div className="w-list-block">
        {element.title ? <p className="w-list-title">{element.title}</p> : null}
        <ul className="w-list">
          {rows.map((row, i) => (
            <li key={i}>
              <span className="w-list-primary">{row.primary ?? ''}</span>
              {row.secondary ? <span className="w-list-secondary">{row.secondary}</span> : null}
              {row.meta ? <span className="w-list-meta">{row.meta}</span> : null}
            </li>
          ))}
        </ul>
      </div>
    );
  }
  if (element.kind === 'table') {
    const rows = (element.rows ?? []) as string[][];
    const columns = element.columns ?? [];
    if (!columns.length) return blank;
    return (
      <div className="w-table-block">
        {element.title ? <p className="w-list-title">{element.title}</p> : null}
        <table className="w-table">
          <thead>
            <tr>{columns.map((column, i) => <th key={i}>{column}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r}>{row.map((cell, c) => <td key={c}>{cell}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (element.kind === 'sparkline' && element.points && element.points.length > 1) {
    const min = Math.min(...element.points);
    const max = Math.max(...element.points);
    const span = max - min || 1;
    const coords = element.points.map((point, index) => {
      const x = (index / (element.points!.length - 1)) * 100;
      const y = 28 - ((point - min) / span) * 24;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return (
      <svg viewBox="0 0 100 30" role="img" aria-label={element.label || 'History'}>
        <polyline points={coords} fill="none" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    );
  }
  if (element.kind === 'status') {
    return (
      <p className={`w-status w-tone-${element.tone || 'ok'}`}>
        {element.text || element.reason || ''}
      </p>
    );
  }
  if (element.kind === 'timeline') {
    const items = (element.items ?? []) as PluginTimelineItem[];
    if (!items.length) return blank;
    return (
      <div className="w-list-block">
        {element.title ? <p className="w-list-title">{element.title}</p> : null}
        <ol className="w-timeline">
          {items.map((item, i) => (
            <li key={i}>
              <span className="w-list-meta">{item.time ?? ''}</span>
              <span className="w-list-primary">{item.title ?? ''}</span>
              {item.meta ? <span className="w-list-secondary">{item.meta}</span> : null}
            </li>
          ))}
        </ol>
      </div>
    );
  }
  if (element.kind === 'checklist') {
    const items = (element.items ?? []) as PluginChecklistItem[];
    if (!items.length) return blank;
    return (
      <div className="w-list-block">
        {element.title ? <p className="w-list-title">{element.title}</p> : null}
        <ul className="w-checklist">
          {items.map((item, i) => (
            <li key={i} className={item.done ? 'is-done' : ''}>
              <span aria-hidden="true">{item.done ? '✓' : '○'}</span>
              <span className="w-list-primary">{item.text ?? ''}</span>
              {item.due ? <span className="w-list-meta">{item.due}</span> : null}
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return <p className="w-note">{element.text ?? element.value ?? ''}</p>;
}

/**
 * The elements this build knows how to draw. A reading that appends
 * anything else draws nothing rather than an empty box, so a newer server
 * degrades quietly.
 */
export function drawableElements(elements: PluginElement[] | undefined): PluginElement[] {
  return (elements ?? []).filter((element) => knownKind(element.kind));
}

/** One citation the drilldown prints: a fact's id and source, or a desk
 * entity's name and fact count. A fact's text never travels, so none can
 * be printed. */
function whyCitation(fact: NonNullable<InsightWhyItem['facts']>[number]): string {
  return 'id' in fact ? `Fact ${fact.id} from ${fact.source}` : `${fact.name}, ${fact.factCount} notes`;
}

/**
 * The receipts block's provenance drilldown: a native disclosure, so the
 * detail costs no script and no space until it is asked for. The entries
 * print as the server bounded them; this is the one markup both tiles'
 * surfaces draw.
 */
function WhyDetails({ items }: { items: InsightWhyItem[] }) {
  return (
    <details className="w-why">
      <summary>Why</summary>
      <ul className="w-why-list">
        {items.map((item, i) => (
          <li key={i}>
            <span className="w-why-claim">{item.claim}</span>
            {item.columns?.length ? <span className="w-why-meta">Columns: {item.columns.join(', ')}</span> : null}
            {item.cells?.length ? <span className="w-why-meta">Cells: {item.cells.join(', ')}</span> : null}
            {item.rule ? <span className="w-why-meta">Rule: {item.rule}</span> : null}
            {item.facts?.length ? (
              <span className="w-why-meta">Cites: {item.facts.map(whyCitation).join(' · ')}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </details>
  );
}

/**
 * The tile's sitting delta line, drawn at the top of the tile whatever its
 * state, an attention tile included. The line is the server's sentence,
 * printed as it came; a tile without one draws nothing.
 */
export function DeltaBanner({ block }: { block: InsightBlock | undefined }) {
  if (!block || block.kind !== 'delta') return null;
  return <p className="w-delta-banner">{block.text}</p>;
}

/**
 * The reading's lines below the elements: receipts (with its why
 * drilldown), falsify and note, in the order the server resolved them. A
 * delta block never renders here (DeltaBanner owns the top of the tile),
 * and a kind this build does not know draws nothing, so a newer server
 * degrades quietly.
 */
export function InsightBlocks({ blocks }: { blocks: InsightBlock[] }) {
  return (
    <>
      {blocks.map((block, i) =>
        block.kind === 'delta' ? null : (
          <Fragment key={i}>
            <p className="w-note">{block.text}</p>
            {block.kind === 'receipts' && block.why?.length ? <WhyDetails items={block.why} /> : null}
          </Fragment>
        ),
      )}
    </>
  );
}

interface PressOfferProps {
  press: InsightPress;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

/**
 * The reading's press: one model call, offered under the reading and spent
 * only when it is pressed. The disclosure arrives with the answer and is
 * drawn above the draft, so no stage action is ever offered before it; a
 * refusal is the desk's own sentence and offers nothing beside it.
 */
export function PressOffer({ press, onRefetch, onExpired }: PressOfferProps) {
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState<'press' | 'stage' | null>(null);
  const [answer, setAnswer] = useState<Partial<InsightAnswer> | null>(null);
  const [refusal, setRefusal] = useState('');
  const [staged, setStaged] = useState<'' | 'staged' | 'existing'>('');
  const [stagedCard, setStagedCard] = useState('');
  const pressPhase =
    press.kind === 'reply-draft'
      ? 'Drafting the reply'
      : press.kind === 'check-counter'
        ? 'Checking the counter-evidence'
        : 'Explaining this range';
  // Nothing shows under 100 ms on either the control or its placeholder,
  // and the answer replaces the placeholder in place.
  const busyShown = useBusy(busy);
  const placeholder = usePhase(busy && action === 'press', pressPhase);
  const faceActions = useFaceActions();

  useFaceActivity({
    mood: 'thinking',
    source: 'request',
    label: action === 'stage' ? 'Staging reply card' : pressPhase,
    active: busy,
  });
  useFaceActivity({
    mood: 'blocked',
    label: refusal || undefined,
    active: Boolean(refusal),
  });

  /**
   * Spend the press: post it once and keep whichever of the answer, the
   * refusal or the staged card came back, clearing whatever the previous
   * press left showing.
   */
  async function send(stage: boolean) {
    setBusy(true);
    setAction(stage ? 'stage' : 'press');
    setRefusal('');
    if (!stage) {
      setAnswer(null);
      setStaged('');
      setStagedCard('');
    }
    // The press travels verbatim: the card's payload is the request, so the
    // SPA spreads it rather than re-assembling it field by field, and stage
    // is the one field a second press adds.
    const { label: _label, route: _route, ...rest } = press;
    const body: PressBody = stage ? { ...rest, stage: true } : rest;
    let result;
    try {
      result = await pressReading(press.route, body);
    } catch {
      setBusy(false);
      setAction(null);
      setRefusal('The dashboard could not reach its own server; nothing was drafted. Try again.');
      return;
    }
    setBusy(false);
    setAction(null);
    if (result.status === 401) {
      onExpired();
      return;
    }
    if (!result.ok) {
      setRefusal(result.data.error || `The desk answered ${result.status} without a sentence; nothing was drafted. Try again.`);
      return;
    }
    if (stage) {
      setStaged(result.data.staged === false ? 'existing' : 'staged');
      setStagedCard(result.data.cardId ?? '');
      await onRefetch();
      faceActions?.notifyDone(result.data.staged === false ? 'Already staged' : 'Reply staged');
      return;
    }
    setStaged('');
    setAnswer(result.data);
    faceActions?.notifyDone(
      press.kind === 'reply-draft'
        ? 'Reply drafted'
        : press.kind === 'check-counter'
          ? 'Counter-evidence checked'
          : 'Range explained',
    );
  }

  const disclosure = answer?.disclosure ?? [];
  const stageOffered = press.kind === 'reply-draft' && answer?.status === 'draft' && !staged;

  return (
    <div className="w-body-inner" aria-busy={busy ? 'true' : undefined}>
      <Button
        tone="secondary"
        className="btn-sm"
        disabled={busy}
        pending={busyShown && action === 'press'}
        pendingLabel={
          press.kind === 'reply-draft'
            ? 'Drafting the reply...'
            : press.kind === 'check-counter'
              ? 'Checking the counter-evidence...'
              : 'Explaining this range...'
        }
        onClick={() => send(false)}
      >
        {press.label}
      </Button>
      {refusal ? <div className="alert" role="alert">{refusal}</div> : null}
      {placeholder.shown ? (
        <PendingBody
          phase={pressPhase}
          slow={placeholder.slow}
          lines={press.kind === 'reply-draft' ? 5 : 3}
          className="w-note press-placeholder"
        />
      ) : null}
      {disclosure.length ? (
        <ul className="w-list" aria-label="What this press sends">
          {disclosure.map((line, i) => (
            <li key={i}>
              <span className="w-list-primary">{line}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {(answer?.text ?? '')
        .split('\n')
        .filter((line) => line.trim())
        .map((line, i) => (
          <p key={i} className="w-note">{line}</p>
        ))}
      {answer?.note ? <p className="w-note">{answer.note}</p> : null}
      {answer?.source ? (
        <p className="w-note">
          Source: <span className="mono">{answer.source}</span>
        </p>
      ) : null}
      {stageOffered ? (
        <Button
          tone="secondary"
          className="btn-sm"
          disabled={busy}
          pending={busyShown && action === 'stage'}
          pendingLabel="Staging..."
          onClick={() => send(true)}
        >
          Stage as a reply card
        </Button>
      ) : null}
      {staged === 'staged' ? (
        <p className="w-note" role="status">{`Staged as a card: ${stagedCard}. Open the inbox to accept or edit it.`}</p>
      ) : null}
      {staged === 'existing' ? (
        <p className="w-note" role="status">
          {`This reply was already staged as a card${stagedCard ? `: ${stagedCard}` : ''}. Open the inbox to accept or edit it.`}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Choose the card's presentation: a tracker card and a setup card both hand
 * off to TrackerCard, an unconfigured install shows the wireframe and its setup
 * link, and a ready card renders its elements, insight and receipt actions.
 */
export default function PluginCardView({ card, onRefetch, onExpired }: PluginCardViewProps) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const faceActions = useFaceActions();

  useFaceActivity({
    mood: 'reading',
    source: 'request',
    label: 'Re-testing the data source',
    active: busy,
  });
  useFaceActivity({
    mood: 'blocked',
    label: note || undefined,
    active: Boolean(note),
  });
  // The wizard asks what a tile should show, so a workbook tile may carry a
  // face other than the classic one. It draws those elements like any other
  // card; the classic tracker card is what a tile without a chosen face gets.
  if (card.payload?.setup
      || (card.payload?.tracker && card.payload?.face !== 'ui-schema')
      || card.id === 'excel-report' || card.id.startsWith('excel-report~')) {
    return <TrackerCard card={card} onRefetch={onRefetch} onExpired={onExpired} />;
  }
  if (card.freshness === 'setup') {
    // Installed, not set up yet: the dotted wireframe and one action.
    const base = card.pluginId || card.id.split('~')[0];
    return (
      <div className="plugin-unset">
        <h3 className="cell-title">{card.title}</h3>
        <WireState
          wide
          line="Installed, not set up. It reads nothing until you choose what it watches."
          action={<Button tone="secondary" className="btn-sm" href={`/marketplace/plugin/${encodeURIComponent(base)}`}>Set up</Button>}
        />
      </div>
    );
  }
  const fresh = card.freshness === 'fresh';
  // A stale source keeps its last good value on the card, but not the live stamp.
  const sourceStale = card.payload?.source?.state === 'stale';
  const stamp = sourceStale
    ? { fresh: false, text: card.checkedAt ? staleSince(card.checkedAt) : 'Stale' }
    : fresh ? { fresh: true, text: 'live' } : { fresh: false, text: 'Re-test available' };
  const elements = fresh ? (card.payload?.elements ?? []) : [];
  // The sitting's delta rides the payload even on an attention tile, so it
  // is read off the card whatever its state; the reading's other lines only
  // render where the tile can stand behind them.
  const deltaBlock = card.payload?.insight?.blocks?.find((block) => block.kind === 'delta');
  const insight = fresh ? card.payload?.insight : undefined;
  const blocks = (insight?.blocks ?? []).filter((block) => block.kind !== 'delta');
  /**
   * Ask the server to run the plugin again, then refresh the card.
   *
   * A 401 expires the session; an unreachable server leaves a note instead of
   * a stale card.
   */
  async function retest() {
    setBusy(true);
    setNote('');
    let res;
    try {
      res = await postJson('/api/marketplace/retest', { id: card.id });
    } catch {
      setBusy(false);
      setNote('The dashboard could not reach its own server; the re-test did not run. Try again.');
      return;
    }
    if (res.status === 401) { setBusy(false); onExpired(); return; }
    if (!res.ok) {
      setBusy(false);
      setNote('The re-test did not run; try again in a moment.');
      return;
    }
    // The dim and the phase line hold until the fresh payload lands, so
    // the reader never sees the old card as if the re-test had finished.
    await onRefetch();
    setBusy(false);
    faceActions?.notifyDone('Re-test complete');
  }

  const menuItems: CardMenuItem[] = fresh
    ? [{ label: 'Manage plugins', href: '/plugins' }]
    : [
        { label: 'Re-test now', onSelect: retest, disabled: busy },
        { label: 'Manage plugins', href: '/plugins' },
      ];

  return (
    <WidgetCard
      title={card.title}
      span="span-4"
      badge={card.pilot ? 'PILOT' : undefined}
      stamp={stamp}
      amber={!fresh}
      menuItems={menuItems}
      foot={`plugin v${card.version}`}
    >
      {busy ? <PhaseLine active text="Re-testing the data source" /> : null}
      <div className={busy ? 'w-body-stack region-busy' : 'w-body-stack'} aria-busy={busy ? 'true' : undefined}>
        <DeltaBanner block={deltaBlock} />
        {fresh && elements.length > 0 ? (
          elements.map((element, i) => <ElementView key={i} element={element} />)
        ) : fresh ? (
          <>
            <p className="w-big">{card.version}</p>
            <p className="w-note">reading the data source</p>
          </>
        ) : (
          <>
            <div className="alert" role="status">
              <p>{card.cause || 'data source has not run'}</p>
              <p>
                Re-test runs the plugin's data source again; the nightly probe
                does the same for every plugin.
              </p>
            </div>
            {note ? <div className="alert" role="alert">{note}</div> : null}
          </>
        )}
        <InsightBlocks blocks={blocks} />
        {card.manualMetric ? (
          <ManualValueForm pluginId={card.manualMetric} onRefetch={onRefetch} onExpired={onExpired} />
        ) : null}
      </div>
      {insight?.press ? (
        <PressOffer press={insight.press} onRefetch={onRefetch} onExpired={onExpired} />
      ) : null}
    </WidgetCard>
  );
}

/**
 * The small form a hand-kept number tile carries.
 *
 * A number nobody can set is a broken tile, so the tile itself asks for one.
 * Saving writes the plugin's own data file through the marketplace route and
 * then refreshes, which is what makes the value appear without a re-test.
 */
function ManualValueForm({ pluginId, onRefetch, onExpired }: {
  pluginId: string;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}) {
  const [value, setValue] = useState('');
  const [unit, setUnit] = useState('');
  const [target, setTarget] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [failed, setFailed] = useState(false);
  const busyShown = useBusy(busy);

  /** Save the typed value, then refresh so the tile shows it. */
  async function save() {
    if (!value.trim()) return;
    setBusy(true);
    setNote('');
    setFailed(false);
    let res;
    try {
      res = await postJson('/api/marketplace/manual-value', {
        id: pluginId, value, unit, target,
      });
    } catch {
      setBusy(false);
      setFailed(true);
      setNote('The desk could not reach its server; the value was not saved. Try again.');
      return;
    }
    if (res.status === 401) { setBusy(false); onExpired(); return; }
    if (!res.ok) {
      setBusy(false);
      setFailed(true);
      const body = res.data as { message?: string } | null;
      setNote(body?.message || 'The value was not saved. Check the value and try again.');
      return;
    }
    setValue('');
    await onRefetch();
    setBusy(false);
    setNote('Saved.');
  }

  return (
    <form className="manual-value" aria-busy={busy ? 'true' : undefined} onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <label className="w-note" htmlFor={`manual-${pluginId}`}>Set the value</label>
      <input id={`manual-${pluginId}`} type="number" inputMode="decimal" value={value}
             onChange={(event) => setValue(event.target.value)} required />
      <input type="text" value={unit} placeholder="Unit" aria-label="Unit"
             onChange={(event) => setUnit(event.target.value)} />
      <input type="number" inputMode="decimal" value={target} placeholder="Target"
             aria-label="Target" onChange={(event) => setTarget(event.target.value)} />
      <Button tone="secondary" type="submit" disabled={busy} pending={busyShown} pendingLabel="Saving...">Save</Button>
      <PhaseLine active={busy} text="Saving the value" className="w-note" />
      {note ? <p className={failed ? 'w-note alert' : 'w-note'} role={failed ? 'alert' : 'status'}>{note}</p> : null}
    </form>
  );
}
