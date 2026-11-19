// One installed plugin's dashboard card, rendered from the payload's
// plugin data (never server HTML). Fresh with a bound payload: the
// host-computed metrics and notes the ui-schema asked for. Fresh
// without one: the version and what it is reading. Attention: the
// cause and the honest note about Re-test, amber. The overflow menu
// re-tests the plugin's data source through the plugin endpoint and
// links the plugins page; the item refuses clicks while one is running.
import { useState } from 'react';
import { postJson, pressReading, type PressBody } from '../api';
import type {
  InsightAnswer,
  InsightPress,
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
import { WireState } from './cells';

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
  const [answer, setAnswer] = useState<Partial<InsightAnswer> | null>(null);
  const [refusal, setRefusal] = useState('');
  const [staged, setStaged] = useState<'' | 'staged' | 'existing'>('');
  const [stagedCard, setStagedCard] = useState('');

  /**
   * Spend the press: post it once and keep whichever of the answer, the
   * refusal or the staged card came back, clearing whatever the previous
   * press left showing.
   */
  async function send(stage: boolean) {
    setBusy(true);
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
      setRefusal('The dashboard could not reach its own server; nothing was drafted.');
      return;
    }
    setBusy(false);
    if (result.status === 401) {
      onExpired();
      return;
    }
    if (!result.ok) {
      setRefusal(result.data.error || `The desk answered ${result.status} without a sentence; nothing was drafted.`);
      return;
    }
    if (stage) {
      setStaged(result.data.staged === false ? 'existing' : 'staged');
      setStagedCard(result.data.cardId ?? '');
      await onRefetch();
      return;
    }
    setStaged('');
    setAnswer(result.data);
  }

  const disclosure = answer?.disclosure ?? [];
  const stageOffered = press.kind === 'reply-draft' && answer?.status === 'draft' && !staged;

  return (
    <div className="w-body-inner">
      <Button tone="secondary" className="btn-sm" disabled={busy} onClick={() => send(false)}>
        {press.label}
      </Button>
      {refusal ? <div className="alert" role="alert">{refusal}</div> : null}
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
        <Button tone="secondary" className="btn-sm" disabled={busy} onClick={() => send(true)}>
          Stage as a reply card
        </Button>
      ) : null}
      {staged === 'staged' ? (
        <p className="w-note">{`Staged as a card: ${stagedCard}. Open the inbox to accept or edit it.`}</p>
      ) : null}
      {staged === 'existing' ? (
        <p className="w-note">
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
  if (card.payload?.setup || card.payload?.tracker || card.id === 'excel-report' || card.id.startsWith('excel-report~')) {
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
  const elements = fresh ? (card.payload?.elements ?? []) : [];
  const insight = fresh ? card.payload?.insight : undefined;
  const blocks = insight?.blocks ?? [];

  /**
   * Ask the server to run the plugin again, then refresh the card.
   *
   * A 401 expires the session; an unreachable server leaves a note instead of
   * a stale card.
   */
  async function retest() {
    setBusy(true);
    let res;
    try {
      res = await postJson(`/api/plugins/${encodeURIComponent(card.id)}/retest`);
    } catch {
      setBusy(false);
      setNote('The dashboard could not reach its own server; the re-test did not run.');
      return;
    }
    setBusy(false);
    if (res.status === 401) { onExpired(); return; }
    await onRefetch();
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
      stamp={fresh ? { fresh: true, text: 'live' } : { fresh: false, text: 'Re-test available' }}
      amber={!fresh}
      menuItems={menuItems}
      foot={`plugin v${card.version}`}
    >
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
          {note ? <div className="alert" role="status">{note}</div> : null}
        </>
      )}
      {blocks.map((block, i) => (
        <p className="w-note" key={i}>
          {block.text}
        </p>
      ))}
      {insight?.press ? (
        <PressOffer press={insight.press} onRefetch={onRefetch} onExpired={onExpired} />
      ) : null}
    </WidgetCard>
  );
}
