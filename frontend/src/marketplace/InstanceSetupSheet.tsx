// The manage view's instance-setup sheet: the shared instance walk
// (open a workbook, assign the columns, pick the rows, confirm) with the
// marketplace's own slots, the create-phase naming step among them. The
// walk drives the same /api/plugins endpoints the dashboard card drives
// through one adapter, so a change to the picker recovery or the
// outside-workspace acceptance lands in both sheets at once.
import { useState } from 'react';
import Button from '../components/Button';
import InstanceWalk, {
  type ConfirmCtx,
  type InstanceWalkRequests,
  type LeadCtx,
  type OpenWay,
  type WalkOpen,
  type WalkSave,
} from '../components/InstanceWalk';
import type { GridPreview } from '../components/RowSelectGrid';
import { MarketApiError, marketErrorText, postInstance, postUpload } from './client';
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

/**
 * Name the file an instance reads, marking one whose setup was never
 * confirmed.
 *
 * Only the final path segment is shown, and an instance with no source path
 * reads as "Not set up" rather than as an empty name.
 */
export function instanceFileName(item: InstanceDocument): string {
  const raw = item.source?.path || '';
  if (!raw) return 'Not set up';
  const base = raw.split(/[\\/]/).pop() || raw;
  return item.confirmedAt ? base : `${base} (not confirmed)`;
}

/** Return the last segment of an instance's source path, or the path itself. */
function baseName(item: InstanceDocument): string {
  const raw = item.source?.path || '';
  return raw.split(/[\\/]/).pop() || raw;
}

const CREATE_STEPS = ['Name the instance', 'Open the workbook', 'Choose what to track'] as const;
const EDIT_STEPS = ['Open the workbook', 'Choose what to track', 'Confirm'] as const;

/**
 * Render the walk that names, opens and confirms one plugin instance.
 *
 * Creating starts at the naming step and editing at opening the workbook;
 * both then assign columns, pick rows and confirm. A staged file outside the
 * workspace folder turns the refusal into a one-time acceptance instead of a
 * dead end, and a picker that cannot open reveals the typed-path and upload
 * ways in, since the sheet's note about a file dialog would no longer be true.
 */
export function InstanceSetupSheet({
  title, pluginName, setupPluginId, target, onCancel, onDone, onChanged,
}: InstanceSetupSheetProps) {
  const isCreate = target.mode === 'create';
  const [instance, setInstance] = useState<InstanceDocument | null>(
    target.mode === 'edit' ? target.instance : null);
  const [name, setName] = useState(
    target.mode === 'edit' ? target.instance.name : '');

  /**
   * The marketplace's throwing client as the walk's open answer; the
   * instance document the open returns is adopted here, since the walk
   * only needs the preview.
   */
  async function open(way: OpenWay): Promise<WalkOpen> {
    const iid = instance?.instanceId;
    if (!iid) return { ok: false, message: 'Name the instance first.' };
    /** The per-instance URL tail every open way posts to. */
    const tail = (suffix: string) => `/${encodeURIComponent(iid)}${suffix}`;
    try {
      if (way.kind === 'pick') {
        const res = await postInstance<{ instance: InstanceDocument; preview: GridPreview }>(
          setupPluginId, tail('/pick'), { name: instance.name });
        setInstance(res.instance);
        return { ok: true, preview: res.preview };
      }
      if (way.kind === 'stage') {
        const res = await postInstance<{ instance: InstanceDocument; preview: GridPreview }>(
          setupPluginId, tail('/stage'), { path: way.path });
        setInstance(res.instance);
        return { ok: true, preview: res.preview };
      }
      const res = await postUpload<{ instance: InstanceDocument; preview: GridPreview }>(
        setupPluginId, tail(`/upload/${encodeURIComponent(way.file.name)}`), way.file);
      setInstance(res.instance);
      return { ok: true, preview: res.preview };
    } catch (err) {
      if (err instanceof MarketApiError && err.code === 'config:picker-unavailable') {
        return { ok: false, message: err.message, pickerDown: true };
      }
      return { ok: false, message: marketErrorText(err) };
    }
  }

  /** A thrown marketplace failure as the walk's save answer. */
  function thrown(err: unknown): WalkSave {
    if (err instanceof MarketApiError && err.code === 'config:outside-workspace') {
      // The dead-end becomes a choice (T6 review): the walk offers the
      // acceptance the API supports, then retries this step.
      return { ok: false, outside: true };
    }
    return { ok: false, message: marketErrorText(err) };
  }

  const requests: InstanceWalkRequests = {
    open,
    confirm: async (choice) => {
      if (!instance) return { ok: false, message: 'Name the instance first.' };
      try {
        await postInstance<{ instance: InstanceDocument }>(
          setupPluginId,
          `/${encodeURIComponent(instance.instanceId)}/confirm`,
          {
            name,
            suggested: false,
            headerRow: 1,
            tracking: {
              labelColumn: choice.labelColumn,
              valueColumn: choice.valueColumn,
              aggregate: 'sum',
              unit: '',
              rows: choice.picked,
              good: 'up',
            },
          });
        return { ok: true };
      } catch (err) {
        return thrown(err);
      }
    },
    acceptOutside: async () => {
      if (!instance) return { ok: false, message: 'Name the instance first.' };
      try {
        await postInstance<{ outsideAccepted: boolean }>(
          setupPluginId,
          `/${encodeURIComponent(instance.instanceId)}/outside`,
          {});
        return { ok: true };
      } catch (err) {
        return thrown(err);
      }
    },
  };

  const statusLabel = instance?.confirmedAt ? 'Confirmed' : 'Needs setup';

  /** The create step: name the instance, then the walk opens the workbook. */
  function lead(ctx: LeadCtx) {
    /** Create the named instance on the server and continue at the open step. */
    const create = async () => {
      await ctx.ask(async () => {
        try {
          const res = await postInstance<{ instance: InstanceDocument }>(setupPluginId, '', { name });
          setInstance(res.instance);
          setName(res.instance.name || name);
          ctx.next();
          onChanged?.();
          return { ok: true };
        } catch (err) {
          return thrown(err);
        }
      });
    };
    return (
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
          <Button tone="primary" disabled={ctx.busy || !name.trim()} onClick={() => void create()}>
            {ctx.busy ? 'Creating…' : 'Create instance'}
          </Button>
        </div>
      </section>
    );
  }

  /** The naming step's body, from the choice the walk carries. */
  function confirmBody(ctx: ConfirmCtx) {
    return (
      <>
        <p className="setup-summary mono">
          {ctx.columns.valueColumn} by {ctx.columns.labelColumn} · {ctx.columns.picked.length} rows
          {instance ? ` · ${baseName(instance)}` : ''}
        </p>
        <label className="setup-field">Name this instance
          <input aria-label="Instance name" value={name}
                 onChange={(event) => setName(event.target.value)} />
        </label>
        {ctx.outside}
        <Button tone="primary" onClick={ctx.save} disabled={ctx.busy || !name.trim()}>
          {ctx.busy ? 'Confirming…' : 'Confirm'}
        </Button>
      </>
    );
  }

  return (
    <InstanceWalk
      title={title}
      onClose={onCancel}
      requests={requests}
      onDone={(choice) => onDone(
        `${name || instance?.name || 'The instance'} now reads ${instance ? baseName(instance) : 'its workbook'}, tracking ${choice.picked.length} rows.`)}
      unreachable="The marketplace could not reach its own server. Try again."
      steps={isCreate ? CREATE_STEPS : EDIT_STEPS}
      stepNumber={isCreate ? { open: 2, choose: 3, confirm: 3 } : { open: 1, choose: 2, confirm: 3 }}
      outsideNoun="instance"
      lead={isCreate ? lead : undefined}
      openLead={(pickerDown) => (
        <>
          <p>
            {isCreate
              ? `${name || instance?.name || 'The instance'} is created. Now point it at its data.`
              : `${instance?.name} currently reads ${instance ? instanceFileName(instance) : 'Not set up'} · ${statusLabel}.`}
          </p>
          {pickerDown ? null : (
            <p className="w-note">
              The file dialog opens on this computer; only the file's name
              comes back.
            </p>
          )}
        </>
      )}
      chooseFooter={(ctx) => (
        <Button tone="primary" className="setup-continue" onClick={ctx.toConfirm} disabled={!ctx.ready}>
          Continue
        </Button>
      )}
      confirmBody={confirmBody}
    />
  );
}
