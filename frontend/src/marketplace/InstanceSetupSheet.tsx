// The manage view's instance-setup sheet: the desk's shared dialog shell
// (ModalSheet) and the shared selection surface (RowSelectGrid) driving
// the same /api/plugins endpoints the dashboard card drives. A new
// instance is named first, then the walk continues in this sheet: open
// a workbook (the server-side picker), assign the columns on the
// preview, choose the rows, and confirm with tracking.rows. Every
// failure surfaces the server's error envelope verbatim, role=alert.
import { useState } from 'react';
import Button from '../components/Button';
import ModalSheet from '../components/ModalSheet';
import RowSelectGrid, { type GridPreview } from '../components/RowSelectGrid';
import { MarketApiError, marketErrorText, postInstance } from './client';
import type { InstanceDocument } from './types';

export type SetupTarget =
  | { mode: 'create' }
  | { mode: 'edit'; instance: InstanceDocument };

interface InstanceSetupSheetProps {
  title: string;
  pluginName: string;
  setupPluginId: string;
  target: SetupTarget;
  onCancel: () => void;
  onDone: (note: string) => void;
  // Fired after a step changes the instance list behind the sheet (a
  // create), so the manage view re-reads while the walk continues.
  onChanged?: () => void;
}

export function instanceFileName(item: InstanceDocument): string {
  const raw = item.source?.path || '';
  if (!raw) return 'Not set up';
  const base = raw.split(/[\\/]/).pop() || raw;
  return item.confirmedAt ? base : `${base} (not confirmed)`;
}

function baseName(item: InstanceDocument): string {
  const raw = item.source?.path || '';
  return raw.split(/[\\/]/).pop() || raw;
}

type Phase = 'name' | 'open' | 'choose' | 'confirm';

const CREATE_STEPS = ['Name the instance', 'Open the workbook', 'Choose what to track'] as const;
const EDIT_STEPS = ['Open the workbook', 'Choose what to track', 'Confirm'] as const;

export function InstanceSetupSheet({
  title, pluginName, setupPluginId, target, onCancel, onDone, onChanged,
}: InstanceSetupSheetProps) {
  const isCreate = target.mode === 'create';
  const [instance, setInstance] = useState<InstanceDocument | null>(
    target.mode === 'edit' ? target.instance : null);
  const [phase, setPhase] = useState<Phase>(isCreate ? 'name' : 'open');
  const [name, setName] = useState(
    target.mode === 'edit' ? target.instance.name : '');
  const [preview, setPreview] = useState<GridPreview | null>(null);
  const [role, setRole] = useState<'value' | 'label'>('value');
  const [valueColumn, setValueColumn] = useState('');
  const [labelColumn, setLabelColumn] = useState('');
  const [picked, setPicked] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // The staged file is outside the workspace folder: the confirm was
  // refused, and the honest inline choice (accept once, retry) is up.
  const [outside, setOutside] = useState(false);

  const steps = isCreate ? CREATE_STEPS : EDIT_STEPS;
  // Each mode numbers its own list: create walks name, open, choose
  // (the confirm block rides step 3); edit starts at open.
  const stepNumber = isCreate
    ? (phase === 'name' ? 1 : phase === 'open' ? 2 : 3)
    : (phase === 'open' ? 1 : phase === 'choose' ? 2 : 3);

  const fail = (err: unknown) => {
    setError(err instanceof MarketApiError ? err.message : marketErrorText(err));
  };

  const create = async () => {
    setBusy(true);
    setError('');
    try {
      const res = await postInstance<{ instance: InstanceDocument }>(setupPluginId, '', { name });
      setInstance(res.instance);
      setName(res.instance.name || name);
      setPhase('open');
      onChanged?.();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const openWorkbook = async () => {
    if (!instance) return;
    setBusy(true);
    setError('');
    try {
      const res = await postInstance<{ instance: InstanceDocument; preview: GridPreview }>(
        setupPluginId,
        `/${encodeURIComponent(instance.instanceId)}/pick`,
        { name: instance.name });
      setInstance(res.instance);
      const next = res.preview;
      setPreview(next);
      // A fresh open starts from every row; the user narrows or clears.
      setPicked(next.rows.map((_row, index) => index));
      setValueColumn('');
      setLabelColumn('');
      setPhase('choose');
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  function assign(header: string) {
    if (role === 'value') setValueColumn(header);
    else setLabelColumn(header);
  }

  const confirm = async () => {
    if (!instance) return;
    setBusy(true);
    setError('');
    try {
      await postInstance<{ instance: InstanceDocument }>(
        setupPluginId,
        `/${encodeURIComponent(instance.instanceId)}/confirm`,
        {
          name,
          suggested: false,
          headerRow: 1,
          tracking: {
            labelColumn,
            valueColumn,
            aggregate: 'sum',
            unit: '',
            rows: picked,
            good: 'up',
          },
        });
      onDone(`${name || instance.name} now reads ${baseName(instance)}, tracking ${picked.length} rows.`);
    } catch (err) {
      if (err instanceof MarketApiError && err.code === 'config:outside-workspace') {
        // The dead-end becomes a choice (T6 review): the sheet offers
        // the acceptance the API supports, then retries this step.
        setOutside(true);
        setError('');
      } else {
        fail(err);
      }
    } finally {
      setBusy(false);
    }
  };

  const acceptOutside = async () => {
    if (!instance) return;
    setBusy(true);
    setError('');
    try {
      await postInstance<{ outsideAccepted: boolean }>(
        setupPluginId,
        `/${encodeURIComponent(instance.instanceId)}/outside`,
        {});
    } catch (err) {
      fail(err);
      setBusy(false);
      return;
    }
    setOutside(false);
    setBusy(false);
    await confirm();
  };

  const statusLabel = instance?.confirmedAt ? 'Confirmed' : 'Needs setup';

  return (
    <ModalSheet open title={title} onClose={onCancel} busy={busy} error={error}>
      <ol className="setup-steps">
        {steps.map((label, index) => {
          const n = index + 1;
          const state = n === stepNumber ? 'is-current' : n < stepNumber ? 'is-done' : '';
          return (
            <li key={label} className={state} aria-current={n === stepNumber ? 'step' : undefined}>
              <span className="setup-step-n">{n}</span><span className="setup-step-label">{label}</span>
            </li>
          );
        })}
      </ol>

      {phase === 'name' ? (
        <section className="setup-open">
          <div className="setup-open-copy">
            <p>
              Name the instance of {pluginName}. Each instance keeps its
              own file, columns, and rows.
            </p>
            <label className="setup-field">Instance name
              <input aria-label="Instance name" value={name}
                     autoComplete="off" spellCheck={false}
                     onChange={(event) => setName(event.target.value)} />
            </label>
            <Button tone="primary" disabled={busy || !name.trim()} onClick={() => void create()}>
              {busy ? 'Creating…' : 'Create instance'}
            </Button>
          </div>
        </section>
      ) : null}

      {phase === 'open' && instance ? (
        <section className="setup-open">
          <div className="setup-open-copy">
            <p>
              {isCreate
                ? `${name || instance.name} is created. Now point it at its data.`
                : `${instance.name} currently reads ${instanceFileName(instance)} · ${statusLabel}.`}
            </p>
            <p className="w-note">
              The file dialog opens on this computer; only the file's name
              comes back.
            </p>
            <Button tone="primary" onClick={() => void openWorkbook()} disabled={busy}>
              {busy ? 'Opening…' : 'Open a workbook'}
            </Button>
          </div>
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
            onSelectedChange={setPicked}
            onAssignHeader={assign}
            valueColumn={valueColumn}
            labelColumn={labelColumn}
          />
          <Button tone="primary" className="setup-continue"
                  onClick={() => setPhase('confirm')}
                  disabled={!labelColumn || !valueColumn || picked.length === 0}>
            Continue
          </Button>
        </section>
      ) : null}

      {phase === 'confirm' && instance ? (
        <section className="setup-name">
          <p className="setup-summary mono">{valueColumn} by {labelColumn} · {picked.length} rows · {baseName(instance)}</p>
          <label className="setup-field">Name this instance
            <input aria-label="Instance name" value={name}
                   onChange={(event) => setName(event.target.value)} />
          </label>
          {outside ? (
            <div className="setup-proposal" role="status">
              <p className="setup-reason">
                That file lives outside the workspace folder. Accept it
                once and this instance can read it.
              </p>
              <div className="setup-actions">
                <Button tone="primary" onClick={() => void acceptOutside()} disabled={busy}>
                  {busy ? 'Accepting…' : 'Use it anyway'}
                </Button>
              </div>
            </div>
          ) : null}
          <Button tone="primary" onClick={() => void confirm()} disabled={busy || !name.trim()}>
            {busy ? 'Confirming…' : 'Confirm'}
          </Button>
        </section>
      ) : null}
    </ModalSheet>
  );
}
