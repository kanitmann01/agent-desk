// Three-step setup sheet: open a workbook, choose columns and rows on a
// preview grid, then name the instance. Suggest highlights a proposal
// and waits for Accept or Adjust. The sheet rides the desk's modal
// shell (scrim, Escape, focus trap, restore) and the grid is the shared
// selection surface (click, drag sweep, shift-click, select all).
import { useEffect, useState } from 'react';
import { getJson, postJson } from '../api';
import Button from '../components/Button';
import ModalSheet from '../components/ModalSheet';
import RowSelectGrid from '../components/RowSelectGrid';
import { WireChart } from './cells';

const STEPS = ['Open', 'Choose what to track', 'Confirm'] as const;

interface Preview {
  headers: string[];
  rows: string[][];
  sheet: string;
}

interface Proposal {
  labelColumn: string;
  valueColumn: string;
  aggregate: string;
  rows?: number[];
  reason?: string;
  source?: string;
}

interface TrackerSetupProps {
  pluginId: string;
  instanceId: string;
  name: string;
  onDone: () => Promise<void>;
  onClose: () => void;
  onExpired: () => void;
}

export default function TrackerSetup({
  pluginId, instanceId, name, onDone, onClose, onExpired,
}: TrackerSetupProps) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [role, setRole] = useState<'value' | 'label'>('value');
  const [labelColumn, setLabelColumn] = useState('');
  const [valueColumn, setValueColumn] = useState('');
  const [picked, setPicked] = useState<number[]>([]);
  const [instanceName, setInstanceName] = useState(name);
  const [unit, setUnit] = useState('');
  const [headersOnly, setHeadersOnly] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [suggested, setSuggested] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  // The opened file is outside the workspace folder: the confirm was
  // refused, and the honest inline choice (accept once, retry) is up.
  const [outside, setOutside] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getJson('/widgets/settings').then((res) => {
      if (cancelled) return;
      if (res.status === 401) { onExpired(); return; }
      const only = Boolean((res.data as { suggest_headers_only?: boolean }).suggest_headers_only);
      setHeadersOnly(only);
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [onExpired]);

  const pickUrl = `/api/plugins/${encodeURIComponent(pluginId)}/instances/${encodeURIComponent(instanceId)}/pick`;
  const suggestUrl = `/api/plugins/${encodeURIComponent(pluginId)}/instances/${encodeURIComponent(instanceId)}/suggest`;
  const confirmUrl = `/api/plugins/${encodeURIComponent(pluginId)}/instances/${encodeURIComponent(instanceId)}/confirm`;
  const outsideUrl = `/api/plugins/${encodeURIComponent(pluginId)}/instances/${encodeURIComponent(instanceId)}/outside`;

  function assign(header: string) {
    if (role === 'value') setValueColumn(header);
    else setLabelColumn(header);
    setProposal(null);
  }

  function chooseRows(rows: number[]) {
    setPicked(rows);
    setProposal(null);
  }

  async function openFile() {
    setBusy(true);
    setError('');
    const res = await postJson(pickUrl, { name });
    setBusy(false);
    if (res.status === 401) { onExpired(); return; }
    if (!res.ok) {
      setError((res.data as { message?: string }).message || 'The file was not opened.');
      return;
    }
    const next = (res.data as { preview: Preview }).preview;
    setPreview(next);
    setPicked(next.rows.map((_row, index) => index));
    setValueColumn('');
    setLabelColumn('');
    setStep(2);
  }

  async function suggest() {
    setBusy(true);
    setError('');
    const res = await postJson(suggestUrl, { headersOnly });
    setBusy(false);
    if (res.status === 401) { onExpired(); return; }
    const data = res.data as { proposal?: Proposal | null; error?: string };
    if (!res.ok || !data.proposal) {
      setError(data.error || 'No suggestion came back.');
      return;
    }
    setProposal(data.proposal);
    setLabelColumn(data.proposal.labelColumn);
    setValueColumn(data.proposal.valueColumn);
    setPicked(data.proposal.rows ?? []);
    setSuggested(true);
  }

  function acceptSuggestion() {
    setProposal(null);
    setStep(3);
  }

  async function confirm() {
    setBusy(true);
    setError('');
    const res = await postJson(confirmUrl, {
      name: instanceName,
      suggested,
      headerRow: 1,
      tracking: {
        labelColumn,
        valueColumn,
        aggregate: 'sum',
        unit,
        rows: picked,
        good: 'up',
      },
    });
    setBusy(false);
    if (res.status === 401) { onExpired(); return; }
    if (!res.ok) {
      if ((res.data as { error?: string }).error === 'config:outside-workspace') {
        // The dead-end becomes a choice (T6 review): the sheet offers
        // the acceptance the API supports, then retries this step.
        setOutside(true);
        setError('');
        return;
      }
      setError((res.data as { message?: string }).message || 'The choice was not saved.');
      return;
    }
    await onDone();
    onClose();
  }

  async function acceptOutside() {
    setBusy(true);
    setError('');
    const res = await postJson(outsideUrl, {});
    setBusy(false);
    if (res.status === 401) { onExpired(); return; }
    if (!res.ok) {
      setError((res.data as { message?: string }).message || 'The choice was not saved.');
      return;
    }
    setOutside(false);
    await confirm();
  }

  return (
    <ModalSheet open title="Set up this tracker" onClose={onClose} busy={busy} error={error}>
      <ol className="setup-steps">
        {STEPS.map((label, index) => {
          const n = (index + 1) as 1 | 2 | 3;
          const state = n === step ? 'is-current' : n < step ? 'is-done' : '';
          return (
            <li key={label} className={state} aria-current={n === step ? 'step' : undefined}>
              <span className="setup-step-n">{n}</span><span className="setup-step-label">{label}</span>
            </li>
          );
        })}
      </ol>
      {step === 1 ? (
        <section className="setup-open">
          <div className="setup-open-copy">
            <p>Open the workbook. Nothing is read until you confirm.</p>
            <dl className="setup-reads">
              <div><dt>Reads</dt><dd>A copy of the file, never the one you work in</dd></div>
              <div><dt>You pick</dt><dd>One value column, a row label and the rows to count</dd></div>
              <div><dt>Shows</dt><dd>The total, its change since the last reading and a sparkline</dd></div>
            </dl>
            <Button tone="primary" onClick={() => void openFile()} disabled={busy}>Open a workbook</Button>
          </div>
          <div className="setup-open-wire"><WireChart bars={8} /></div>
        </section>
      ) : null}
      {step === 2 && preview ? (
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
          <div className="setup-suggest">
            <p data-testid="suggest-disclosure">
              {headersOnly
                ? `Sends the headers ${preview.headers.join(', ')}. No cell values and no file path leave this machine.`
                : `Sends the headers ${preview.headers.join(', ')} and ${Math.min(preview.rows.length, 5)} rows. The file path stays on this machine.`}
            </p>
            <Button tone="secondary" onClick={() => void suggest()} disabled={busy}>Suggest what to track</Button>
          </div>
          {proposal ? (
            <div className="setup-proposal" role="status">
              <p className="setup-reason">
                {proposal.source === 'heuristic' ? 'Suggested on this machine. ' : ''}
                {proposal.reason}
              </p>
              <div className="setup-actions">
                <Button tone="primary" onClick={acceptSuggestion}>Accept</Button>
                <Button tone="secondary" onClick={() => setProposal(null)}>Adjust</Button>
              </div>
            </div>
          ) : (
            <Button tone="primary" className="setup-continue" onClick={() => setStep(3)} disabled={!labelColumn || !valueColumn || picked.length === 0}>
              Continue
            </Button>
          )}
        </section>
      ) : null}
      {step === 3 ? (
        <section className="setup-name">
          <p className="setup-summary mono">{valueColumn} by {labelColumn} · {picked.length} rows</p>
          <label className="setup-field">Name this tracker
            <input aria-label="Instance name" value={instanceName} onChange={(event) => setInstanceName(event.target.value)} />
          </label>
          <label className="setup-field">Unit
            <input aria-label="Unit" value={unit} onChange={(event) => setUnit(event.target.value)} placeholder="USD" />
          </label>
          {outside ? (
            <div className="setup-proposal" role="status">
              <p className="setup-reason">
                That file lives outside the workspace folder. Accept it
                once and this tracker can read it.
              </p>
              <div className="setup-actions">
                <Button tone="primary" onClick={() => void acceptOutside()} disabled={busy}>
                  {busy ? 'Accepting…' : 'Use it anyway'}
                </Button>
              </div>
            </div>
          ) : null}
          <Button tone="primary" onClick={() => void confirm()} disabled={busy || !instanceName.trim()}>Confirm</Button>
        </section>
      ) : null}
    </ModalSheet>
  );
}
