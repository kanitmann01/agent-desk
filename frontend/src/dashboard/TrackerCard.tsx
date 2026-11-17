// The workbook tracker on the desk: a status and one action. The setup
// sheet is separate. A live card is the instance name, one figure, the
// signed change, a sparkline, and the file name.
import { useState } from 'react';
import type { PluginCard } from '../types';
import Button from '../components/Button';
import TrackerSetup from './TrackerSetup';

interface TrackerCardProps {
  card: PluginCard;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

function Sparkline({ points }: { points: number[] }) {
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const coords = points.map((point, index) => {
    const x = (index / (points.length - 1)) * 100;
    const y = 28 - ((point - min) / span) * 24;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg className="tracker-spark" viewBox="0 0 100 32" role="img" aria-label="Recent readings">
      <polyline points={coords} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

export default function TrackerCard({ card, onRefetch, onExpired }: TrackerCardProps) {
  const [open, setOpen] = useState(false);
  const tracker = card.payload?.tracker;
  const setup = card.payload?.setup;
  const live = Boolean(tracker) && card.freshness === 'fresh';

  return (
    <article className="tracker-live">
      {live && tracker ? (
        <>
          <header className="tracker-head">
            <h2>{tracker.name}</h2>
            <Button tone="secondary" onClick={() => setOpen(true)}>Edit</Button>
          </header>
          <div className="kpi">
            <div className={`value${tracker.direction === 'down' ? ' down' : ''}${tracker.direction === 'flat' ? ' flat' : ''}`}>
              {tracker.value}
              {tracker.unit ? <span className="tracker-unit">{tracker.unit}</span> : null}
            </div>
          </div>
          <p className={tracker.direction === 'down' ? 'tracker-delta down' : tracker.direction === 'up' ? 'tracker-delta up' : 'tracker-delta'}>
            {tracker.delta === 'First reading' ? 'First reading' : `${tracker.delta} since the last reading`}
          </p>
          {tracker.goal ? (
            <p className="brief-quiet">Goal {tracker.goal.value}{tracker.goal.unit ? ` ${tracker.goal.unit}` : ''}</p>
          ) : null}
          {tracker.paceNote ? <p className="brief-quiet">{tracker.paceNote}</p> : null}
          {tracker.points.length >= 2 ? <Sparkline points={tracker.points} /> : null}
          <p className="tracker-file">{tracker.file}</p>
        </>
      ) : (
        <>
          <h2>{card.title || 'Workbook tracker'}</h2>
          <p className="brief-quiet">No workbook is connected, so there is nothing to track.</p>
          <Button tone="primary" onClick={() => setOpen(true)}>Set up</Button>
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
    </article>
  );
}
