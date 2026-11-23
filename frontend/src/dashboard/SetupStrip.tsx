// The Get started strip (spec 022): the three steps between a fresh desk
// and the morning loop, in the order a person takes them, each one click.
// The steps and their done flags are the server's setup object, the one
// truth the Decisions cell used to guess at on its own. The strip holds no
// primary: the question bar keeps the surface's one action, and it reads
// "Connect your AI" until the first step is done. The stepper is the
// tracker sheet's (numbered square, accent when done), so a person meets
// one stepper language twice.
import { useState, type ReactNode } from 'react';
import type { SetupData, SetupStep } from '../types';
import Button from '../components/Button';
import { postJson } from '../api';
import type { WorkbookConnect } from './useWorkbookConnect';

/** What the one click of each open step is called. */
const STEP_VERBS: Record<SetupStep['id'], string> = { ai: 'Add', workbook: 'Open', calendar: 'Connect' };

const CHECK = (
  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 8.5 6.5 12 13 4.5" />
  </svg>
);

interface SetupStripProps {
  setup: SetupData;
  /** Hide the strip for this sitting; the header then offers Finish setup. */
  onDismiss: () => void;
  /** Reload the dashboard once the sample switch has answered. */
  onRefetch: () => Promise<void>;
  onExpired: () => void;
  /** The shared connect walk: the server's picker, then the typed path. */
  workbook: WorkbookConnect;
}

/**
 * The Get started strip: three steps in order, the sample offer, and a way
 * to hide it for now.
 *
 * The workbook step goes through the shared connect walk; the other two are
 * links. The sample switch posts the settings toggle the way the Settings
 * page does. It is offered while nothing real is connected, and named with
 * a way to hide it while the sample set is in use.
 */
export default function SetupStrip({ setup, onDismiss, onRefetch, onExpired, workbook }: SetupStripProps) {
  const [sampleBusy, setSampleBusy] = useState(false);
  const [sampleNote, setSampleNote] = useState('');
  const steps = setup.steps;
  const doneCount = steps.filter((step) => step.done).length;
  const firstOpen = steps.find((step) => !step.done)?.id;
  const nothingConnected = doneCount === 0;

  /** Turn sample data on or off, then reload the dashboard once. */
  async function toggleSample() {
    setSampleBusy(true);
    try {
      const res = await postJson('/settings/toggle', { key: 'sample_data' });
      if (res.status === 401) { onExpired(); return; }
      const body = (res.data ?? {}) as { error?: string };
      if (!res.ok || body.error) {
        setSampleNote(setup.sample
          ? 'Sample data did not turn off. Try again.'
          : 'Sample data did not turn on. Try again.');
        return;
      }
      setSampleNote('');
      await onRefetch();
    } catch {
      setSampleNote('The dashboard could not reach its own server; sample data did not change.');
    } finally {
      setSampleBusy(false);
    }
  }

  /** The one click of one step: a button, a link, or the word Done. */
  function stepAction(step: SetupStep): ReactNode {
    if (step.done) return <span className="gs-state">Done</span>;
    if (step.id === 'workbook') {
      return (
        <Button tone="secondary" className="btn-sm" disabled={workbook.busy}
          onClick={() => void workbook.pick()}>
          {STEP_VERBS.workbook}
        </Button>
      );
    }
    return <Button tone="secondary" className="btn-sm" href={step.href}>{STEP_VERBS[step.id]}</Button>;
  }

  return (
    <section className="cell cell-get-started" id="get-started" tabIndex={-1} aria-labelledby="get-started-title">
      <div className="cell-head">
        <span className="tag">GET STARTED</span>
        <span className="cell-meta">{doneCount} of {steps.length} done</span>
        <button type="button" className="text-btn gs-dismiss" onClick={onDismiss}>Not now</button>
      </div>
      <h2 className="cell-title" id="get-started-title">Three steps and your desk is ready</h2>
      <ol className="gs-steps">
        {steps.map((step, index) => (
          <li
            key={step.id}
            className={step.done ? 'gs-step is-done' : 'gs-step'}
            aria-current={step.id === firstOpen ? 'step' : undefined}
          >
            <span className="gs-mark" aria-hidden="true">{step.done ? CHECK : index + 1}</span>
            <span className="gs-head">
              <span className="gs-title">{step.title}</span>
              <span className="gs-action">{stepAction(step)}</span>
            </span>
            <span className="gs-why">{step.reason}</span>
          </li>
        ))}
      </ol>
      {setup.sample || nothingConnected ? (
        <p className="gs-foot">
          {setup.sample ? 'You are looking at sample data. ' : 'Nothing is connected yet. '}
          <button type="button" className="text-btn" disabled={sampleBusy}
            onClick={() => void toggleSample()}>
            {setup.sample ? 'Hide sample data' : 'Try it with sample data'}
          </button>
        </p>
      ) : null}
      {sampleNote ? <p className="alert" role="status">{sampleNote}</p> : null}
      {workbook.note ? <p className="alert" role="status">{workbook.note}</p> : null}
      {workbook.manualOpen ? (
        <div className="well">
          <input
            className="well-input"
            type="text"
            name="workbook-path"
            autoComplete="off"
            aria-label="Workbook path"
            placeholder="Full path to the workbook…"
            value={workbook.pathInput}
            onChange={(e) => workbook.setPathInput(e.target.value)}
            onKeyDown={workbook.onPathKey}
          />
          <button className="btn btn-primary btn-sm" type="button" disabled={workbook.busy}
            onClick={() => void workbook.connect(workbook.pathInput.trim())}>
            Connect
          </button>
        </div>
      ) : null}
    </section>
  );
}
