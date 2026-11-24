// The workbook tracker on the desk. Live: the tracker pattern (name,
// figure, signed change, trend line, pace to the goal, file), then the
// reading the server appended: its elements through the same view the
// generic plugin card uses, its resolved lines, and the press when the
// workbook family offered one. Not set up: the dotted wireframe with one
// Set up action. The setup sheet is separate and opens over the desk, and
// it opens from every card shape: the server's setup card, a live
// tracker's Edit, and the amber card of a confirmed tracker whose
// workbook moved (that one carries only the cause, no payload at all).
import { useState } from 'react';
import type { PluginCard, PluginElement, PluginSetup } from '../types';
import Button from '../components/Button';
import TrackerSetup from './TrackerSetup';
import { drawableElements, ElementView, PressOffer } from './PluginCardView';
import { TrackerFigure, WireState } from './cells';

interface TrackerCardProps {
  card: PluginCard;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

/**
 * The workbook tracker: the live figure with its Edit action, or the setup prompt.
 *
 * The setup sheet opens from either shape, falling back to the card's own ids when the
 * payload carries no setup step.
 */
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
  // The tile already owns the value, the change, the workbook, the pace and
  // the history chart. The same facts arrive again as elements for the
  // generic renderer; drawing both is the duplicate face this card had. A
  // wizard-built tracker chose its own face, so its elements are not the
  // classic five and it keeps drawing them as before.
  const wizardFace = live && card.payload?.face === 'ui-schema';
  /** True for an element that only says again what the tile itself draws. */
  const restatesTile = (element: PluginElement): boolean =>
    (element.kind === 'metric' && element.label === 'Value')
    || (element.kind === 'delta' && element.label === 'Change')
    || (element.kind === 'text' && (element.label === 'Workbook' || element.label === 'Pace'))
    || (element.kind === 'sparkline' && element.label === 'History');
  const faceElements = live ? drawableElements(card.payload?.elements) : [];
  const reading = wizardFace ? [] : faceElements.filter((element) => !restatesTile(element));
  const insight = live ? card.payload?.insight : undefined;
  const press = insight?.press ?? null;
  const blocks = insight?.blocks ?? [];
  const firstReading = reading[0];
  const firstBlock = blocks[0];
  const restReading = reading.slice(1);
  const restBlocks = firstReading ? blocks : blocks.slice(1);
  const hasReading = !wizardFace && (reading.length > 0 || blocks.length > 0);

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
      {wizardFace ? (
        <>
          {faceElements.map((element, i) => (
            <ElementView key={i} element={element} />
          ))}
          {blocks.map((block, i) => (
            <p className="w-note" key={i}>
              {block.text}
            </p>
          ))}
        </>
      ) : hasReading ? (
        <section className="tracker-reading" aria-label="What this reading says">
          <p className="tracker-reading-title">What this reading says</p>
          {firstReading
            ? <ElementView element={firstReading} />
            : <p className="w-note">{firstBlock.text}</p>}
          {restReading.length > 0 || restBlocks.length > 0 ? (
            <details className="tracker-reading-more">
              <summary>More of this reading</summary>
              {restReading.map((element, i) => (
                <ElementView key={i} element={element} />
              ))}
              {restBlocks.map((block, i) => (
                <p className="w-note" key={i}>
                  {block.text}
                </p>
              ))}
            </details>
          ) : null}
        </section>
      ) : null}
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
