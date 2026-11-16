// The workbook tracker's first run: open a file, confirm columns, done.
// Suggest sits on the column step. The disclosure is the sentence that
// names what leaves the machine, shown before the button is pressed.
import { useEffect, useState } from 'react';
import { getJson, postJson } from '../api';

interface Preview {
  headers: string[];
  rows: string[][];
  sheet: string;
  sheets: string[];
}

interface Proposal {
  labelColumn: string;
  valueColumn: string;
  aggregate: string;
}

interface TrackerSetupProps {
  pluginId: string;
  instanceId: string;
  name: string;
  onDone: () => Promise<void>;
  onExpired: () => void;
}

export default function TrackerSetup({ pluginId, instanceId, name, onDone, onExpired }: TrackerSetupProps) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [labelColumn, setLabelColumn] = useState('');
  const [valueColumn, setValueColumn] = useState('');
  const [aggregate, setAggregate] = useState('sum');
  const [headerRow, setHeaderRow] = useState('1');
  const [rangeText, setRangeText] = useState('');
  const [paceOn, setPaceOn] = useState(false);
  const [plan, setPlan] = useState('');
  const [periodDays, setPeriodDays] = useState('');
  const [elapsedDays, setElapsedDays] = useState('');
  const [headersOnly, setHeadersOnly] = useState(false);
  const [disclosure, setDisclosure] = useState(
    'This sends the column names and up to 5 rows to the company endpoint. The file path stays on this machine.',
  );
  const [suggested, setSuggested] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getJson('/widgets/settings').then((res) => {
      if (cancelled) return;
      if (res.status === 401) { onExpired(); return; }
      const data = res.data as { suggest_headers_only?: boolean };
      const only = Boolean(data.suggest_headers_only);
      setHeadersOnly(only);
      setDisclosure(only
        ? 'This sends the column names to the company endpoint. No cell values and no file path leave this machine.'
        : 'This sends the column names and up to 5 rows to the company endpoint. The file path stays on this machine.');
    }).catch(() => {
      if (!cancelled) setError('The dashboard could not reach its own server.');
    });
    return () => { cancelled = true; };
  }, [onExpired]);

  async function openFile() {
    setBusy(true);
    setError('');
    const res = await postJson(`/api/plugins/${encodeURIComponent(pluginId)}/instances/${encodeURIComponent(instanceId)}/pick`, { name });
    setBusy(false);
    if (res.status === 401) { onExpired(); return; }
    if (!res.ok) {
      const data = res.data as { message?: string };
      setError(data.message || 'The file was not opened.');
      return;
    }
    const data = res.data as { preview: Preview };
    setPreview(data.preview);
    setLabelColumn(data.preview.headers[0] || '');
    setValueColumn(data.preview.headers[1] || data.preview.headers[0] || '');
  }

  async function suggest() {
    setBusy(true);
    setError('');
    const res = await postJson(`/api/plugins/${encodeURIComponent(pluginId)}/instances/${encodeURIComponent(instanceId)}/suggest`, { headersOnly });
    setBusy(false);
    if (res.status === 401) { onExpired(); return; }
    const data = res.data as { disclosure?: string; proposal?: Proposal | null; error?: string };
    if (data.disclosure) setDisclosure(data.disclosure);
    if (!res.ok || data.error || !data.proposal) {
      setError(data.error || 'No suggestion came back. Pick the columns yourself.');
      return;
    }
    setLabelColumn(data.proposal.labelColumn);
    setValueColumn(data.proposal.valueColumn);
    setAggregate(data.proposal.aggregate || 'sum');
    setSuggested(true);
  }

  async function confirm() {
    setBusy(true);
    setError('');
    const tracking: Record<string, unknown> = {
      labelColumn, valueColumn, aggregate, good: 'up',
    };
    if (paceOn) {
      tracking.pace = {
        plan: Number(plan),
        periodDays: Number(periodDays),
        elapsedDays: Number(elapsedDays),
      };
    }
    const res = await postJson(`/api/plugins/${encodeURIComponent(pluginId)}/instances/${encodeURIComponent(instanceId)}/confirm`, {
      tracking, suggested, headerRow: Number(headerRow) || 1, range: rangeText,
    });
    setBusy(false);
    if (res.status === 401) { onExpired(); return; }
    if (!res.ok) {
      const data = res.data as { message?: string };
      setError(data.message || 'The columns were not saved.');
      return;
    }
    await onDone();
  }

  return (
    <div className="tracker-setup">
      <p className="w-note">Step 1. Open a workbook. Step 2. Pick the columns. Step 3. Confirm.</p>
      <p className="w-note" data-testid="suggest-disclosure">{disclosure}</p>
      {!preview ? (
        <button type="button" className="btn btn-primary" onClick={() => void openFile()} disabled={busy}>
          Open a workbook
        </button>
      ) : (
        <>
          <p className="w-note">{preview.sheet}: {preview.rows.length} preview rows</p>
          <label className="field">Header row
            <input aria-label="Header row" value={headerRow} onChange={(event) => setHeaderRow(event.target.value)} />
          </label>
          <label className="field">Range
            <input aria-label="Range" value={rangeText} onChange={(event) => setRangeText(event.target.value)} placeholder="A1:F40" />
          </label>
          <label className="field">Label column
            <select aria-label="Label column" value={labelColumn} onChange={(event) => setLabelColumn(event.target.value)}>
              {preview.headers.map((header) => <option key={header} value={header}>{header}</option>)}
            </select>
          </label>
          <label className="field">Value column
            <select aria-label="Value column" value={valueColumn} onChange={(event) => setValueColumn(event.target.value)}>
              {preview.headers.map((header) => <option key={header} value={header}>{header}</option>)}
            </select>
          </label>
          <label className="field">
            <input type="checkbox" checked={paceOn} onChange={(event) => setPaceOn(event.target.checked)} />
            Compare pace
          </label>
          {paceOn ? (
            <div>
              <label className="field">Plan
                <input aria-label="Plan" value={plan} onChange={(event) => setPlan(event.target.value)} />
              </label>
              <label className="field">Days in period
                <input aria-label="Days in period" value={periodDays} onChange={(event) => setPeriodDays(event.target.value)} />
              </label>
              <label className="field">Days elapsed
                <input aria-label="Days elapsed" value={elapsedDays} onChange={(event) => setElapsedDays(event.target.value)} />
              </label>
            </div>
          ) : null}
          <div className="cardrow">
            <button type="button" className="btn btn-secondary" onClick={() => void suggest()} disabled={busy}>
              Suggest what to track
            </button>
            <button type="button" className="btn btn-primary" onClick={() => void confirm()} disabled={busy || !labelColumn || !valueColumn}>
              Confirm
            </button>
          </div>
        </>
      )}
      {error ? <div className="alert" role="status">{error}</div> : null}
    </div>
  );
}
