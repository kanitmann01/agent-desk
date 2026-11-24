// The describe door on Find plugins. The button is a plain form submit, which
// is the whole path without JavaScript: the server's walk asks for the words.
// With JavaScript the click first asks whether an AI connection can fill the
// choices in. When it can, a dialog collects the description, shows the fill
// happening, and hands the manager the walk with the fields preselected. When
// it cannot, the form submits as it always did.
import { useRef, useState, type FormEvent } from 'react';
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
  | { kind: 'closed' }
  | { kind: 'writing' }
  | { kind: 'asking' }
  | { kind: 'filled'; fields: FilledField[]; sessionId: string }
  | { kind: 'failed'; message: string };

/**
 * The describe control: a plain form post that offers a fill when it can.
 *
 * The availability probe runs on the click, not on render, so opening the
 * Plugins page makes no request it did not make before and the offline
 * behaviour of the page is unchanged.
 */
export default function DescribePlugin() {
  const [phase, setPhase] = useState<Phase>({ kind: 'closed' });
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  /**
   * Ask whether a fill is possible, then open the dialog or submit the form.
   *
   * A failed probe is treated as "no fill": the plain walk is always a valid
   * outcome, and it never depends on the AI being reachable.
   */
  async function onClick(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    let autofill = false;
    try {
      const probe = await getJson('/api/wizard/availability');
      autofill = Boolean(probe.ok && (probe.data as { autofill?: boolean } | null)?.autofill);
    } catch {
      autofill = false;
    }
    if (!autofill) {
      formRef.current?.submit();
      return;
    }
    setPhase({ kind: 'writing' });
  }

  /** Fill the choices from the description and show what it chose. */
  async function onFill() {
    const words = description.trim();
    if (!words) return;
    setPhase({ kind: 'asking' });
    setBusy(true);
    try {
      const res = await postJson('/wizard/start', { description: words });
      const body = res.ok
        ? res.data as { id?: string; answers?: Record<string, string>;
                        reasons?: Record<string, string> } | null
        : null;
      const fields = filledFields(body?.answers ?? {}, body?.reasons ?? {});
      if (!res.ok || !body?.id || fields.length === 0) {
        // A refused or empty fill is an honest no-fill: say so, and offer
        // the walk rather than claiming anything was chosen.
        setPhase({ kind: 'failed',
          message: 'The fill did not run. Your questions are ready with nothing preselected.' });
        setBusy(false);
        return;
      }
      setPhase({ kind: 'filled', fields, sessionId: body.id });
    } catch {
      setPhase({ kind: 'failed',
        message: 'The dashboard could not reach its own server; the fill did not run.' });
    }
    setBusy(false);
  }

  /** Go to the walk, where every filled choice is preselected and editable. */
  function continueToWalk() {
    if (phase.kind === 'filled') window.location.assign(`/wizard/${phase.sessionId}`);
  }

  return (
    <>
      <form ref={formRef} method="post" action="/wizard/start" className="mkt-describe"
            onSubmit={onClick}>
        <Button tone="secondary" type="submit">Describe a plugin in plain English</Button>
      </form>

      <ModalSheet
        open={phase.kind !== 'closed'}
        title={phase.kind === 'filled' ? 'Choices filled in' : 'Reading your description'}
        busy={phase.kind === 'asking'}
        onClose={() => { if (!busy) setPhase({ kind: 'closed' }); }}
      >
        {phase.kind === 'writing' ? (
          <div className="mkt-fill">
            <label className="mkt-fill-prompt" htmlFor="mkt-describe-words">
              Describe the plugin you want
            </label>
            <input id="mkt-describe-words" type="text" className="mkt-describe-input"
                   value={description} autoComplete="off"
                   placeholder="A morning list of my mail, or last week's sales by region"
                   onChange={(event) => setDescription(event.target.value)} />
            <div className="mkt-fill-actions">
              <Button tone="primary" onClick={() => { void onFill(); }}>Fill it in for me</Button>
            </div>
          </div>
        ) : null}

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
