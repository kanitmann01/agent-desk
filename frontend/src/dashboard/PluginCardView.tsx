// One installed plugin's dashboard card, rendered from the payload's
// plugin data (never server HTML). Fresh with a bound payload: the
// host-computed metrics and notes the ui-schema asked for. Fresh
// without one: the version and what it is reading. Attention: the
// cause and the honest note about Re-test, amber. The overflow menu
// re-tests the plugin's data source through the plugin endpoint and
// links the plugins page; the item refuses clicks while one is running.
import { useState } from 'react';
import { postJson } from '../api';
import type { PluginCard, PluginChecklistItem, PluginElement, PluginListRow, PluginTimelineItem } from '../types';
import WidgetCard, { type CardMenuItem } from '../components/WidgetCard';
import TrackerCard from './TrackerCard';
import Button from '../components/Button';
import { WireState } from './cells';

interface PluginCardViewProps {
  card: PluginCard;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

function ElementView({ element }: { element: PluginElement }) {
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
    </WidgetCard>
  );
}
