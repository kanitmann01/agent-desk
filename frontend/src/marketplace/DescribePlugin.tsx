// The describe door on Find plugins. Without an AI connection it is the
// plain form post the no-JS walk already accepts. With one, submitting opens
// a dialog that shows the description filling the tile's choices in, then
// hands the manager straight to that walk with the fields presellected.
import { useEffect, useRef, useState, type FormEvent } from 'react';
import Button from '../components/Button';
import ModalSheet from '../components/ModalSheet';
import { getJson, postJson } from '../api';

/** One row of the fill: the field, its chosen label, and the why. */
interface FilledField {
  key: string;
  prompt: string;
  label: string;
  reason: string;
}

const FIELD_PROMPTS: Record<string, string> = {
  source: 'What it watches',
  detail: 'What it reads',
  show: 'What it shows',
  look: 'How it looks',
  update: 'When it updates',
};

const FIELD_ORDER = ['source', 'detail', 'show', 'look', 'update'];

/** The filled answers as display rows, in the order the walk asks them. */
function filledFields(answers: Record<string, string>, reasons: Record<string, string>): FilledField[] {
  return FIELD_ORDER.filter((key) => typeof answers[key] === 'string' && answers[key].trim())
    .map((key) => ({
      key,
      prompt: FIELD_PROMPTS[key] ?? key,
      label: answers[key],
      reason: typeof reasons[key] === 'string' ? reasons[key] : '',
    }));
}

type Phase =
  | { kind: 'idle' }
  | { kind: 'asking' }
  | { kind: 'filled'; fields: FilledField[]; sessionId: string }
  | { kind: 'failed'; message: string };

/**
 * The describe control: a plain form post until an AI connection exists.
 *
 * The availability probe runs on mount. It is one read-only request; when it
 * fails or answers false the form stays a plain post, which is the walk a
 * manager without a connection needs.
 */
export default function DescribePlugin() {
  const [autofill, setAutofill] = useState(false);
  const [description, setDescription] = useState('');
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    let cancelled = false;
    getJson('/api/wizard/availability')
      .then((res) => {
        if (cancelled) return;
        const body = res.ok ? (res.data as { autofill?: boolean } | null) : null;
        setAutofill(Boolean(body?.autofill));
      })
      .catch(() => {
        // No probe, no dialog: the plain post is the safe default.
        if (!cancelled) setAutofill(false);
      });
    return () => { cancelled = true; };
  }, []);

  /**
   * Submit through the dialog when a connection is present.
   *
   * The server does the fill; this only shows it happening and then hands the
   * manager the walk with their answers already selected. A failed fill opens
   * the same walk with nothing preselected, never an error wall.
   */
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    if (!autofill) return; // the native post carries the walk
    event.preventDefault();
    const words = description.trim();
    if (!words) return;
    setPhase({ kind: 'asking' });
    setBusy(true);
    try {
      const res = await postJson('/wizard/start', { description: words });
      if (!res.ok) {
        setPhase({ kind: 'failed',
          message: 'The fill did not run. Your questions are ready with nothing preselected.' });
        setBusy(false);
        return;
      }
      const body = res.data as {
        id?: string; answers?: Record<string, string>; reasons?: Record<string, string>;
      } | null;
      const fields = filledFields(body?.answers ?? {}, body?.reasons ?? {});
      if (!body?.id || fields.length === 0) {
        // An honest no-fill: go to the walk rather than claim anything.
        window.location.assign('/wizard/start');
        return;
      }
      setPhase({ kind: 'filled', fields, sessionId: body.id });
    } catch {
      setPhase({ kind: 'failed',
        message: 'The dashboard could not reach its own server; the fill did not run.' });
    }
    setBusy(false);
  }

  function continueToWalk() {
    if (phase.kind === 'filled') window.location.assign(`/wizard/${phase.sessionId}`);
  }

  return (
    <>
      <form ref={formRef} method="post" action="/wizard/start" className="mkt-describe"
            onSubmit={onSubmit}>
        {autofill ? (
          <label className="mkt-sr-only" htmlFor="mkt-describe-words">
            Describe the plugin you want
          </label>
        ) : null}
        {autofill ? (
          <input id="mkt-describe-words" type="text" className="mkt-describe-input"
                 value={description} autoComplete="off"
                 placeholder="A morning list of my mail, or last week's sales by region"
                 onChange={(event) => setDescription(event.target.value)} />
        ) : null}
        <Button tone="secondary" type="submit" disabled={busy}>
          Describe a plugin in plain English
        </Button>
      </form>

      <ModalSheet
        open={phase.kind === 'asking' || phase.kind === 'filled' || phase.kind === 'failed'}
        title={phase.kind === 'filled' ? 'Choices filled in' : 'Reading your description'}
        busy={phase.kind === 'asking'}
        onClose={() => { if (!busy) setPhase({ kind: 'idle' }); }}
      >
        {phase.kind === 'asking' || phase.kind === 'filled' ? (
          <div className="mkt-fill" aria-live="polite">
            {phase.kind === 'asking'
              ? FIELD_ORDER.map((key) => (
                  <div className="mkt-fill-row" key={key}>
                    <span className="mkt-fill-prompt">{FIELD_PROMPTS[key]}</span>
                    <span className="mkt-skel mkt-fill-skel" aria-hidden="true" />
                  </div>
                ))
              : phase.fields.map((field) => (
                  <div className="mkt-fill-row mkt-fill-done" key={field.key}>
                    <span className="mkt-fill-prompt">{field.prompt}</span>
                    <span className="mkt-fill-label">{field.label}</span>
                    {field.reason ? <p className="mkt-fill-why">{field.reason}</p> : null}
                  </div>
                ))}
          </div>
        ) : null}

        {phase.kind === 'filled' ? (
          <>
            <p className="mkt-fill-note" role="status">
              Filled in from your description. Change anything that is off.
            </p>
            <div className="mkt-fill-actions">
              <Button tone="primary" onClick={continueToWalk}>Change or continue</Button>
            </div>
          </>
        ) : null}

        {phase.kind === 'failed' ? (
          <>
            <p className="mkt-fill-note" role="alert">{phase.message}</p>
            <div className="mkt-fill-actions">
              <Button tone="primary" href="/wizard/start">Continue without the fill</Button>
            </div>
          </>
        ) : null}
      </ModalSheet>
    </>
  );
}
