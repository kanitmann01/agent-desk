// One installed plugin's dashboard card, rendered from the payload's
// plugin data (never server HTML). Fresh with a bound payload: the
// host-computed metrics and notes the ui-schema asked for. Fresh
// without one: the version and what it is reading. Attention: the
// cause and the honest note about Re-test, amber. The overflow menu
// re-tests the plugin's data source through the plugin endpoint and
// links the plugins page; the item refuses clicks while one is running.
import { useState } from 'react';
import { postJson } from '../api';
import type { PluginCard, PluginElement } from '../types';
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
  if (element.kind === 'metric') {
    return (
      <>
        <p className="w-big">{element.value ?? ''}</p>
        {element.label ? <p className="w-note">{element.label}</p> : null}
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
