// The workbook tracker on the desk. Live: the tracker pattern (name,
// figure, signed change, trend line, pace to the goal, file), then the
// reading the server appended — its elements through the same view the
// generic plugin card uses, the receipt line, and the press when the
// workbook family offered one. Not set up: the dotted wireframe with one
// Set up action. The setup sheet is separate and opens over the desk, and
// it opens from every card shape: the server's setup card, a live
// tracker's Edit, and the amber card of a confirmed tracker whose
// workbook moved (that one carries only the cause, no payload at all).
import { useState } from 'react';
import type { PluginCard, PluginSetup } from '../types';
import Button from '../components/Button';
import TrackerSetup from './TrackerSetup';
import { drawableElements, ElementView, PressOffer, receiptLine } from './PluginCardView';
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
  // Never gate the sheet on the payload: an attention card (workbook
  // missing, locked, or unreadable) sends no setup step, and the click
  // used to do nothing at all. Fall back to the card's own ids so the
  // sheet always opens onto the instance it belongs to.
  const sheet: PluginSetup = setup ?? {
    pluginId: card.pluginId || 'excel-report',
    instanceId: card.instanceId || 'main',
    name: tracker?.name || card.title || 'Workbook tracker',
    step: '',
  };
  const line = card.cause
    ? card.cause
    : 'Pick a workbook and the column to follow. Nothing is read until you confirm.';
  // The reading rides on a live card's payload only: an attention card has
  // no payload at all, and a stale one would draw elements it can no longer
  // stand behind. Nothing here draws a box of its own, so a card without a
  // reading renders exactly as it did before.
  const elements = live ? drawableElements(card.payload?.elements) : [];
  const insight = live ? card.payload?.insight : undefined;
  const press = insight?.press ?? null;
  const receipt = insight?.receipts ? receiptLine(insight.receipts) : '';

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
            line={line}
            action={<Button tone="primary" className="btn-sm" onClick={() => setOpen(true)}>Set up</Button>}
          />
        </>
      )}
      {elements.map((element, i) => (
        <ElementView key={i} element={element} />
      ))}
      {receipt ? <p className="w-note">{receipt}</p> : null}
      {press ? <PressOffer press={press} onRefetch={onRefetch} onExpired={onExpired} /> : null}
      {open ? (
        <TrackerSetup
          pluginId={sheet.pluginId}
          instanceId={sheet.instanceId}
          name={sheet.name}
          onDone={onRefetch}
          onClose={() => setOpen(false)}
          onExpired={onExpired}
        />
      ) : null}
    </div>
  );
}
