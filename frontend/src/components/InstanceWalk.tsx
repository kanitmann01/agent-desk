// The shared instance-setup walk: open a workbook (the server's picker,
// a typed path or an upload), assign the columns and pick the rows on
// the preview grid, then confirm. The dashboard's tracker sheet and the
// marketplace's instance sheet are this walk with app-specific slots
// (the tracker's suggest and evaluate steps, the marketplace's create
// phase), so the guarded requests, the picker-unavailable recovery and
// the outside-workspace acceptance exist once and cannot drift again.
// The app-specific requests arrive as an adapter: each call returns the
// walk's answer shape, so the walk never knows which transport (or
// which app) is behind it.
import { useState, type ReactNode } from 'react';
import Button from './Button';
import ModalSheet from './ModalSheet';
import RowSelectGrid, { type GridPreview } from './RowSelectGrid';

/** One of the three ways a workbook gets opened. */
export type OpenWay =
  | { kind: 'pick' }
  | { kind: 'stage'; path: string }
  | { kind: 'upload'; file: File };

/** An open attempt's answer: the preview grid, or the sentence to show. */
export type WalkOpen =
  | { ok: true; preview: GridPreview }
  | { ok: false; message?: string; pickerDown?: boolean };

/** A save attempt's answer: done, the sentence to show, or the
 *  outside-workspace acceptance the confirm was refused for. */
export type WalkSave =
  | { ok: true }
  | { ok: false; message?: string; outside?: boolean };

/** The chosen columns and rows the confirm saves. */
export interface WalkChoice {
  labelColumn: string;
  valueColumn: string;
  picked: number[];
}

/** The requests the walk drives, one adapter per app. */
export interface InstanceWalkRequests {
  open: (way: OpenWay) => Promise<WalkOpen>;
  confirm: (choice: WalkChoice) => Promise<WalkSave>;
  acceptOutside: () => Promise<WalkSave>;
}

/** A guarded request whose failure lands in the shared error slot. */
export type WalkAsk = (request: () => Promise<WalkSave>) => Promise<WalkSave | undefined>;

/** A guarded request whose failure is the caller's to handle: undefined
 *  when the request never completed. */
export type WalkTry = <T>(request: () => Promise<T>) => Promise<T | undefined>;

/** What the choose step's footer may drive. */
export interface ChooseCtx {
  busy: boolean;
  /** Both columns are assigned and at least one row is picked. */
  ready: boolean;
  /** The preview grid the step is showing. */
  preview: GridPreview;
  /** The chosen columns and rows as they stand. */
  choice: WalkChoice;
  /** Move to the confirm step. */
  toConfirm: () => void;
  /** Adopt a proposed choice (a suggestion, a recommendation) as it stands. */
  adopt: (choice: WalkChoice) => void;
  ask: WalkAsk;
  try: WalkTry;
}

/** What the confirm step's body may drive. */
export interface ConfirmCtx {
  busy: boolean;
  columns: WalkChoice;
  /** The outside-workspace acceptance block, placed where the caller wants it. */
  outside: ReactNode;
  /** Run the guarded confirm. */
  save: () => void;
}

/** What an optional first phase (the marketplace's create step) may drive. */
export interface LeadCtx {
  busy: boolean;
  ask: WalkAsk;
  /** Leave the lead phase and start the walk's open step. */
  next: () => void;
}

interface InstanceWalkProps {
  title: string;
  onClose: () => void;
  requests: InstanceWalkRequests;
  /** Runs after a successful confirm, with the choice that was saved. */
  onDone: (choice: WalkChoice) => void;
  /** The sentence for a request that never reached the server. */
  unreachable: string;
  /** The sheet's step labels, as the walk's own header renders them. */
  steps: readonly string[];
  /** The 1-based step number each walk phase shows (a lead phase offsets them). */
  stepNumber: { open: number; choose: number; confirm: number };
  /** The copy above the open buttons; pickerDown says the dialog could not open. */
  openLead?: (pickerDown: boolean) => ReactNode;
  /** The decoration beside the open copy, when the caller wants one. */
  openTrail?: ReactNode;
  /** An optional first phase before the walk starts (create mode). */
  lead?: (ctx: LeadCtx) => ReactNode;
  /** The choose step's tail: the caller's continue machinery. */
  chooseFooter: (ctx: ChooseCtx) => ReactNode;
  /** The confirm step's body: the caller's fields, the outside block, its confirm button. */
  confirmBody: (ctx: ConfirmCtx) => ReactNode;
  /** The noun the outside-acceptance copy names ("this tracker"). */
  outsideNoun: string;
  /** Called when a header is assigned or the picked rows change, so the caller drops its pending suggestion or review. */
  onChoiceChanged?: () => void;
}

type Phase = 'lead' | 'open' | 'choose' | 'confirm';

/**
 * Render the workbook walk inside the desk's modal shell.
 *
 * Every request runs guarded: busy clears whatever happens, failures land
 * in the sheet's error slot, and the outside-workspace refusal becomes
 * the inline accept-once choice instead of a dead end.
 */
export default function InstanceWalk({
  title, onClose, requests, onDone, unreachable, steps, stepNumber,
  openLead, openTrail, lead, chooseFooter, confirmBody, outsideNoun, onChoiceChanged,
}: InstanceWalkProps) {
  const [phase, setPhase] = useState<Phase>(lead ? 'lead' : 'open');
  const [preview, setPreview] = useState<GridPreview | null>(null);
  const [role, setRole] = useState<'value' | 'label'>('value');
  const [labelColumn, setLabelColumn] = useState('');
  const [valueColumn, setValueColumn] = useState('');
  const [picked, setPicked] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // The opened file is outside the workspace folder: the confirm was
  // refused, and the honest inline choice (accept once, retry) is up.
  const [outside, setOutside] = useState(false);
  // The Open step's second way in: a disclosure the user can open, and
  // the picker's own fallback when the dialog could not open.
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [pickerDown, setPickerDown] = useState(false);
  const [typedPath, setTypedPath] = useState('');
  const [fileToUpload, setFileToUpload] = useState<File | null>(null);

  /** The current choice, as the confirm payload and onDone receive it. */
  const choice: WalkChoice = { labelColumn, valueColumn, picked };

  /**
   * Run one request under the walk's guard; a rejection becomes the
   * caller's unreachable sentence instead of an escaped promise.
   */
  async function tryRun<T>(request: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError('');
    try {
      return await request();
    } catch {
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  /** A guarded request whose failure lands in the shared error slot. */
  async function ask(request: () => Promise<WalkSave>): Promise<WalkSave | undefined> {
    const answer = await tryRun(request);
    if (answer !== undefined && !answer.ok && answer.message) setError(answer.message);
    return answer;
  }

  /**
   * One tail for every way in: the dialog's pick, a typed path and an
   * uploaded file all land on the same preview grid.
   */
  async function runOpen(way: OpenWay) {
    setBusy(true);
    setError('');
    let answer: WalkOpen;
    try {
      answer = await requests.open(way);
    } catch {
      answer = { ok: false, message: unreachable };
    }
    setBusy(false);
    if (answer.ok) {
      setPreview(answer.preview);
      setPicked(answer.preview.rows.map((_row, index) => index));
      setValueColumn('');
      setLabelColumn('');
      // The chosen path and file were consumed by this open; a later
      // open must not start with a stale selection.
      setTypedPath('');
      setFileToUpload(null);
      setPhase('choose');
      return;
    }
    if (answer.pickerDown) {
      setPickerDown(true);
      setRecoveryOpen(true);
    }
    if (answer.message) setError(answer.message);
  }

  /**
   * Save the choice and hand a success to onDone; a file outside the
   * workspace folder turns the refusal into the acceptance choice.
   */
  async function runConfirm() {
    setBusy(true);
    setError('');
    let answer: WalkSave;
    try {
      answer = await requests.confirm(choice);
    } catch {
      answer = { ok: false, message: unreachable };
    }
    setBusy(false);
    if (answer.ok) {
      onDone(choice);
      return;
    }
    if (answer.outside) {
      setOutside(true);
      return;
    }
    if (answer.message) setError(answer.message);
  }

  /**
   * Accept a file outside the workspace folder once, then retry the
   * confirm that was blocked.
   */
  async function runAcceptOutside() {
    setBusy(true);
    setError('');
    let answer: WalkSave;
    try {
      answer = await requests.acceptOutside();
    } catch {
      answer = { ok: false, message: unreachable };
    }
    if (answer.ok) {
      setOutside(false);
      await runConfirm();
      return;
    }
    setBusy(false);
    if (answer.message) setError(answer.message);
  }

  /**
   * Give a clicked header the role the toggle names; the choice then
   * counts as the user's own.
   */
  function assign(header: string) {
    if (role === 'value') setValueColumn(header);
    else setLabelColumn(header);
    onChoiceChanged?.();
  }

  /** Replace the picked rows; the choice then counts as the user's own. */
  function chooseRows(rows: number[]) {
    setPicked(rows);
    onChoiceChanged?.();
  }

  /**
   * Adopt a proposed choice wholesale: a suggestion's columns and rows
   * become the standing choice, without counting as a user edit (the
   * proposal itself stays on screen until accepted).
   */
  function adopt(next: WalkChoice) {
    setLabelColumn(next.labelColumn);
    setValueColumn(next.valueColumn);
    setPicked(next.picked);
  }

  const stepOfPhase: Record<Phase, number> = {
    lead: 1,
    open: stepNumber.open,
    choose: stepNumber.choose,
    confirm: stepNumber.confirm,
  };
  const ready = Boolean(labelColumn) && Boolean(valueColumn) && picked.length > 0;

  return (
    <ModalSheet open title={title} onClose={onClose} busy={busy} error={error}>
      <ol className="setup-steps">
        {steps.map((label, index) => {
          const n = index + 1;
          const state = n === stepOfPhase[phase] ? 'is-current' : n < stepOfPhase[phase] ? 'is-done' : '';
          return (
            <li key={label} className={state} aria-current={n === stepOfPhase[phase] ? 'step' : undefined}>
              <span className="setup-step-n">{n}</span><span className="setup-step-label">{label}</span>
            </li>
          );
        })}
      </ol>

      {phase === 'lead' && lead ? lead({
        busy,
        ask,
        next: () => setPhase('open'),
      }) : null}

      {phase === 'open' ? (
        <section className="setup-open">
          <div className="setup-open-copy">
            {openLead?.(pickerDown)}
            <Button tone="primary" onClick={() => void runOpen({ kind: 'pick' })} disabled={busy}>
              {busy ? 'Opening…' : 'Open a workbook'}
            </Button>
            <Button
              aria-expanded={recoveryOpen}
              onClick={() => setRecoveryOpen((open) => !open)}
              disabled={busy}
            >
              Type a path or upload instead
            </Button>
            {recoveryOpen && (
              <div className="setup-choose">
                <div className="setup-actions">
                  <label className="setup-field">
                    Workbook path
                    <input
                      aria-label="Workbook path"
                      value={typedPath}
                      onChange={(event) => setTypedPath(event.target.value)}
                      disabled={busy}
                    />
                  </label>
                  <Button
                    onClick={() => void runOpen({ kind: 'stage', path: typedPath.trim() })}
                    disabled={busy || typedPath.trim() === ''}
                  >
                    Use this path
                  </Button>
                </div>
                <div className="setup-actions">
                  <label className="setup-field">
                    Workbook file
                    <input
                      type="file"
                      aria-label="Workbook file"
                      accept=".xlsx,.xlsm,.csv,.json"
                      onChange={(event) => setFileToUpload(event.target.files?.[0] ?? null)}
                      disabled={busy}
                    />
                  </label>
                  <Button
                    onClick={() => {
                      const file = fileToUpload;
                      if (file) void runOpen({ kind: 'upload', file });
                    }}
                    disabled={busy || fileToUpload === null}
                  >
                    Upload this file
                  </Button>
                </div>
              </div>
            )}
          </div>
          {openTrail}
        </section>
      ) : null}

      {phase === 'choose' && preview ? (
        <section className="setup-choose">
          <div className="setup-toolbar">
            <div className="seg" role="radiogroup" aria-label="A click on a column header assigns">
              <span className="seg-label">Header click sets</span>
              <button type="button" role="radio" aria-checked={role === 'value'} className="seg-btn" onClick={() => setRole('value')}>Value column</button>
              <button type="button" role="radio" aria-checked={role === 'label'} className="seg-btn" onClick={() => setRole('label')}>Row label</button>
            </div>
            <p className="setup-assignment">
              <span className="pick-chip is-value"><span className="pick-k">VALUE</span>{valueColumn || 'not chosen'}</span>
              <span className="pick-chip is-label"><span className="pick-k">LABEL</span>{labelColumn || 'not chosen'}</span>
            </p>
          </div>
          <RowSelectGrid
            preview={preview}
            selected={picked}
            onSelectedChange={chooseRows}
            onAssignHeader={assign}
            valueColumn={valueColumn}
            labelColumn={labelColumn}
          />
          {chooseFooter({
            busy,
            ready,
            preview,
            choice,
            toConfirm: () => setPhase('confirm'),
            adopt,
            ask,
            try: tryRun,
          })}
        </section>
      ) : null}

      {phase === 'confirm' ? (
        <section className="setup-name">
          {confirmBody({
            busy,
            columns: choice,
            outside: outside ? (
              <div className="setup-proposal" role="status">
                <p className="setup-reason">
                  That file lives outside the workspace folder. Accept it
                  once and this {outsideNoun} can read it.
                </p>
                <div className="setup-actions">
                  <Button tone="primary" onClick={() => void runAcceptOutside()} disabled={busy}>
                    {busy ? 'Accepting…' : 'Use it anyway'}
                  </Button>
                </div>
              </div>
            ) : null,
            save: () => void runConfirm(),
          })}
        </section>
      ) : null}
    </ModalSheet>
  );
}
