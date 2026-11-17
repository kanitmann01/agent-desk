// The workbook tracker on the desk. Live: the tracker pattern (name,
// figure, signed change, trend line, pace to the goal, file). Not set
// up: the dotted wireframe with one Set up action. The setup sheet is
// separate and opens over the desk.
import { useState } from 'react';
import type { PluginCard } from '../types';
import Button from '../components/Button';
import TrackerSetup from './TrackerSetup';
import { TrackerFigure, WireState } from './cells';

interface TrackerCardProps {
  card: PluginCard;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

export default function TrackerCard({ card, onRefetch, onExpired }: TrackerCardProps) {
  const [open, setOpen] = useState(false);
  const tracker = card.payload?.tracker;
  const setup = card.payload?.setup;
  const live = Boolean(tracker) && card.freshness === 'fresh';

  return (
    <div className="tracker-card">
      {live && tracker ? (
        <TrackerFigure
          view={tracker}
          action={<Button tone="secondary" className="btn-sm" onClick={() => setOpen(true)}>Edit</Button>}
        />
      ) : (
        <>
          <h3 className="cell-title">{card.title || 'Workbook tracker'}</h3>
          <WireState
            line="Pick a workbook and the column to follow. Nothing is read until you confirm."
            action={<Button tone="primary" className="btn-sm" onClick={() => setOpen(true)}>Set up</Button>}
          />
        </>
      )}
      {open && setup ? (
        <TrackerSetup
          pluginId={setup.pluginId}
          instanceId={setup.instanceId}
          name={setup.name}
          onDone={onRefetch}
          onClose={() => setOpen(false)}
          onExpired={onExpired}
        />
      ) : null}
      {open && !setup && tracker ? (
        <TrackerSetup
          pluginId={card.pluginId || 'excel-report'}
          instanceId={card.instanceId || 'main'}
          name={tracker.name}
          onDone={onRefetch}
          onClose={() => setOpen(false)}
          onExpired={onExpired}
        />
      ) : null}
    </div>
  );
}
