// Three-step setup sheet: open a workbook, choose columns and rows on a
// preview grid, then name the instance. Suggest highlights a proposal
// and waits for Accept or Adjust.
import { useEffect, useState } from 'react';
import { getJson, postJson } from '../api';
import Button from '../components/Button';

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

  function assign(header: string) {
    if (role === 'value') setValueColumn(header);
    else setLabelColumn(header);
    setProposal(null);
  }

  function toggleRow(index: number) {
    setPicked((current) => (
      current.includes(index) ? current.filter((item) => item !== index) : [...current, index].sort((a, b) => a - b)
    ));
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
      setError((res.data as { message?: string }).message || 'The choice was not saved.');
      return;
    }
    await onDone();
    onClose();
  }

  return (
    <div className="setup-scrim">
      <div className="setup-sheet" role="dialog" aria-modal="true" aria-labelledby="setup-title">
        <header className="setup-head">
          <h2 id="setup-title">Set up this tracker</h2>
          <Button tone="secondary" onClick={onClose}>Close</Button>
        </header>
        <ol className="setup-steps">
          <li className={step === 1 ? 'is-current' : ''}>1. Open</li>
          <li className={step === 2 ? 'is-current' : ''}>2. Choose what to track</li>
          <li className={step === 3 ? 'is-current' : ''}>3. Confirm</li>
        </ol>
        {step === 1 ? (
          <section>
            <p>Open the workbook. Nothing is read until you confirm.</p>
            <Button tone="primary" onClick={() => void openFile()} disabled={busy}>Open a workbook</Button>
          </section>
        ) : null}
        {step === 2 && preview ? (
          <section className="setup-choose">
            <fieldset className="setup-role">
              <legend>A click on a column header assigns</legend>
              <label><input type="radio" name="role" checked={role === 'value'} onChange={() => setRole('value')} /> Value column</label>
              <label><input type="radio" name="role" checked={role === 'label'} onChange={() => setRole('label')} /> Row label</label>
            </fieldset>
            <p className="setup-assignment">
              Value: {valueColumn || 'not chosen'}. Label: {labelColumn || 'not chosen'}.
            </p>
            <div className="setup-table-wrap">
              <table className="preview-grid">
                <caption>{preview.sheet}, first {preview.rows.length} rows</caption>
                <thead>
                  <tr>
                    <th scope="col">Track</th>
                    {preview.headers.map((header) => (
                      <th
                        key={header}
                        scope="col"
                        className={header === valueColumn ? 'is-value' : header === labelColumn ? 'is-label' : ''}
                      >
                        <button type="button" onClick={() => assign(header)}>{header}</button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row, index) => (
                    <tr key={index} className={picked.includes(index) ? 'is-picked' : ''}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Track row ${index + 1}`}
                          checked={picked.includes(index)}
                          onChange={() => toggleRow(index)}
                        />
                      </td>
                      {preview.headers.map((header, column) => (
                        <td key={header} className={header === valueColumn ? 'is-value' : header === labelColumn ? 'is-label' : ''}>
                          {row[column] ?? ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
              <Button tone="primary" onClick={() => setStep(3)} disabled={!labelColumn || !valueColumn || picked.length === 0}>
                Continue
              </Button>
            )}
          </section>
        ) : null}
        {step === 3 ? (
          <section className="setup-name">
            <label className="setup-field">Name this tracker
              <input aria-label="Instance name" value={instanceName} onChange={(event) => setInstanceName(event.target.value)} />
            </label>
            <label className="setup-field">Unit
              <input aria-label="Unit" value={unit} onChange={(event) => setUnit(event.target.value)} placeholder="USD" />
            </label>
            <Button tone="primary" onClick={() => void confirm()} disabled={busy || !instanceName.trim()}>Confirm</Button>
          </section>
        ) : null}
        {error ? <p className="alert" role="status">{error}</p> : null}
      </div>
    </div>
  );
}
