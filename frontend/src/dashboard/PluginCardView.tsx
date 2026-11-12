// One installed plugin's dashboard card, rendered from the payload's
// plugin data (never server HTML). Fresh: the version and what it is
// reading. Attention: the cause and the honest note about Re-test, amber.
// The overflow menu re-tests the plugin's data source through the
// plugin endpoint; the item refuses clicks while one is running.
import { useState } from 'react';
import { postJson } from '../api';
import type { PluginCard } from '../types';
import WidgetCard, { type CardMenuItem } from '../components/WidgetCard';

interface PluginCardViewProps {
  card: PluginCard;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

export default function PluginCardView({ card, onRefetch, onExpired }: PluginCardViewProps) {
  const fresh = card.freshness === 'fresh';
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');

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
    ? [{ label: 'Open settings', href: '/settings' }]
    : [
        { label: 'Re-test now', onSelect: retest, disabled: busy },
        { label: 'Open settings', href: '/settings' },
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
      {fresh ? (
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
