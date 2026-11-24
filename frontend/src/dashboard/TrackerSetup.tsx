// The tracker setup sheet: the shared instance walk (open a workbook,
// choose columns and rows, confirm) with the tracker's own slots, the
// suggest proposal and the endpoint's evaluate check among them. The
// walk owns the guarded requests, the picker recovery and the
// outside-workspace acceptance; this file only adapts the dashboard's
// API envelope onto the walk's answers.
import { useEffect, useRef, useState } from 'react';
import { postFile, postJson, type ApiResult } from '../api';
import Button from '../components/Button';
import InstanceWalk, {
  type ChooseCtx,
  type ConfirmCtx,
  type InstanceWalkRequests,
  type OpenWay,
  type WalkOpen,
  type WalkSave,
} from '../components/InstanceWalk';
import { ChartSketch } from './cells';

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
  dateColumn?: string | null;
  chart?: string;
  rows?: number[];
  reason?: string;
  source?: string;
}

type ChartKind = 'line' | 'column' | 'area';

/** A chart name the sheet can store, or line when the value is anything else. */
function asChart(value: string | undefined): ChartKind {
  return value === 'column' || value === 'area' ? value : 'line';
}

/** The skeleton's one line: the metric, the time column or each reading, and the chart. */
function sketchCaption(metric: string, time: string, chart: string): string {
  const shape = chart === 'column' ? 'columns' : chart === 'area' ? 'an area' : 'a line';
  const by = time ? `by ${time}` : 'each reading';
  return `${metric || 'The metric'}, ${by}, as ${shape}`;
}

/** One suggestion request per opened preview. */
function AskOnce({ run }: { run: () => void }) {
  const once = useRef(false);
  useEffect(() => {
    if (once.current) return;
    once.current = true;
    run();
  }, [run]);
  return null;
}

interface TrackerSetupProps {
  pluginId: string;
  instanceId: string;
  name: string;
  onDone: () => Promise<void>;
  onClose: () => void;
  onExpired: () => void;
}

/**
 * The three-step setup sheet: open a workbook, choose the columns and rows on a
 * preview grid, then name the instance.
 *
 * onDone runs once the server has saved the choice and before the sheet closes;
 * onClose dismisses it; onExpired hands a 401 back to the desk.
 */
export default function TrackerSetup({
  pluginId, instanceId, name, onDone, onClose, onExpired,
}: TrackerSetupProps) {
  const [instanceName, setInstanceName] = useState(name);
  const [unit, setUnit] = useState('');
  const [timeColumn, setTimeColumn] = useState('');
  const [chart, setChart] = useState<ChartKind>('line');
  const [aggregate, setAggregate] = useState('sum');
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const asked = useRef('');
  const [disclosure, setDisclosure] = useState('');
  const [suggested, setSuggested] = useState(false);

  const base = `/api/plugins/${encodeURIComponent(pluginId)}/instances/${encodeURIComponent(instanceId)}`;
  const pickUrl = `${base}/pick`;
  const suggestUrl = `${base}/suggest`;
  const confirmUrl = `${base}/confirm`;
  const outsideUrl = `${base}/outside`;
  const stageUrl = `${base}/stage`;
  // The file name is a path segment: the server drops the query string
  // before routing, so an encoded name is the only place it survives.
  const uploadUrl = `${base}/upload/`;

  /** The dashboard's envelope as the walk's open answer. */
  function openAnswer(res: ApiResult): WalkOpen {
    if (res.status === 200) {
      const next = (res.data as { preview: Preview }).preview;
      return { ok: true, preview: next };
    }
    if (res.status === 401) { onExpired(); return { ok: false }; }
    if (res.status === 503 && (res.data as { error?: string }).error === 'config:picker-unavailable') {
      return {
        ok: false,
        message: (res.data as { message?: string }).message || 'The file dialog could not open on this computer.',
        pickerDown: true,
      };
    }
    return { ok: false, message: (res.data as { message?: string }).message || 'The file was not opened.' };
  }

  /** One open request, caught like every call the desk makes. */
  async function open(way: OpenWay): Promise<WalkOpen> {
    try {
      if (way.kind === 'pick') return openAnswer(await postJson(pickUrl, { name }));
      if (way.kind === 'stage') return openAnswer(await postJson(stageUrl, { path: way.path }));
      return openAnswer(await postFile(uploadUrl + encodeURIComponent(way.file.name), way.file));
    } catch {
      return { ok: false, message: 'The dashboard could not reach its own server; the workbook was not opened.' };
    }
  }

  /** The confirm refusal as the walk's save answer. */
  function saveAnswer(res: ApiResult): WalkSave {
    if (res.status === 401) { onExpired(); return { ok: false }; }
    if ((res.data as { error?: string }).error === 'config:outside-workspace') {
      // The dead-end becomes a choice (T6 review): the walk offers the
      // acceptance the API supports, then retries this step.
      return { ok: false, outside: true };
    }
    return { ok: false, message: (res.data as { message?: string }).message || 'The choice was not saved.' };
  }

  const requests: InstanceWalkRequests = {
    open,
    confirm: async (choice) => {
      try {
        const res = await postJson(confirmUrl, {
          name: instanceName,
          suggested,
          headerRow: 1,
          tracking: {
            labelColumn: choice.labelColumn,
            valueColumn: choice.valueColumn,
            dateColumn: timeColumn || null,
            chart,
            aggregate,
            unit,
            rows: choice.picked.length ? choice.picked : null,
            good: 'up',
          },
        });
        if (res.ok) return { ok: true };
        return saveAnswer(res);
      } catch {
        return { ok: false, message: 'The dashboard could not reach its own server; the choice was not saved.' };
      }
    },
    acceptOutside: async () => {
      try {
        const res = await postJson(outsideUrl, {});
        if (res.ok) return { ok: true };
        return saveAnswer(res);
      } catch {
        return { ok: false, message: 'The dashboard could not reach its own server; the choice was not saved.' };
      }
    },
  };

  /**
   * Ask once for this preview. No proposal is the manual sheet, not an error.
   * A network failure still fills the sheet's error slot.
   */
  async function suggest(ctx: ChooseCtx) {
    const token = ctx.preview.headers.join('\n');
    if (asked.current === token) return;
    asked.current = token;
    await ctx.ask(async () => {
      let res;
      try {
        res = await postJson(suggestUrl, {});
      } catch {
        return { ok: false, message: 'The dashboard could not reach its own server; nothing was suggested.' };
      }
      if (res.status === 401) { onExpired(); return { ok: false }; }
      const data = res.data as { proposal?: Proposal | null; disclosure?: string };
      if (!res.ok || !data.proposal) return { ok: true };
      setDisclosure(data.disclosure || '');
      setProposal(data.proposal);
      return { ok: true };
    });
  }

  /** Fill the controls from the suggestion and move to the naming step. */
  function acceptSuggestion(ctx: ChooseCtx, next: Proposal) {
    setChart(asChart(next.chart));
    setTimeColumn(next.dateColumn || '');
    setAggregate(next.aggregate || 'sum');
    setProposal(null);
    setSuggested(true);
    ctx.adopt({
      labelColumn: next.labelColumn,
      valueColumn: next.valueColumn,
      picked: [],
    });
    ctx.toConfirm();
  }

  /** Drop a pending suggestion once the person edits a control. */
  function clearSuggestion() {
    setProposal(null);
    setSuggested(false);
  }

  /** The naming step's body, from the choice the walk carries. */
  function confirmBody(ctx: ConfirmCtx) {
    return (
      <>
        <ChartSketch chart={chart} caption={sketchCaption(ctx.columns.valueColumn, timeColumn, chart)} />
        <p className="setup-summary mono">{ctx.columns.valueColumn} by {ctx.columns.labelColumn} · {ctx.columns.picked.length ? `${ctx.columns.picked.length} rows` : 'every row'}</p>
        <label className="setup-field">Name this tracker
          <input aria-label="Instance name" value={instanceName} onChange={(event) => setInstanceName(event.target.value)} />
        </label>
        <label className="setup-field">Unit
          <input aria-label="Unit" value={unit} onChange={(event) => setUnit(event.target.value)} placeholder="USD" />
        </label>
        {ctx.outside}
        <Button tone="primary" onClick={ctx.save} disabled={ctx.busy || !instanceName.trim()}>Confirm</Button>
      </>
    );
  }

  return (
    <InstanceWalk
      title="Set up this tracker"
      onClose={onClose}
      requests={requests}
      onDone={() => { void (async () => { await onDone(); onClose(); })(); }}
      unreachable="The dashboard could not reach its own server; nothing was saved."
      steps={STEPS}
      stepNumber={{ open: 1, choose: 2, confirm: 3 }}
      outsideNoun="tracker"
      openLead={() => (
        <>
          <p>Open the workbook. Nothing is read until you confirm.</p>
          <dl className="setup-reads">
            <div><dt>Reads</dt><dd>A copy of the file, never the one you work in</dd></div>
            <div><dt>You pick</dt><dd>A metric, an optional time column, and a line, columns, or an area</dd></div>
            <div><dt>Shows</dt><dd>That chart, from the workbook when a time column is set</dd></div>
          </dl>
        </>
      )}
      openTrail={(
        <div className="setup-open-wire">
          <ChartSketch chart="line" caption="The metric, each reading, as a line" />
        </div>
      )}
      allowEmptyRows
      onChoiceChanged={() => {
        setProposal(null);
        setSuggested(false);
      }}
      chooseLead={(ctx) => (
        <ChartSketch
          chart={proposal?.chart || chart}
          caption={sketchCaption(
            proposal?.valueColumn || ctx.choice.valueColumn,
            proposal ? (proposal.dateColumn || '') : timeColumn,
            proposal?.chart || chart,
          )}
        />
      )}
      chooseFooter={(ctx) => (
        <>
          <AskOnce run={() => void suggest(ctx)} />
          <div className="setup-suggest">
            <label className="setup-field">Time column
              <select aria-label="Time column" value={proposal ? (proposal.dateColumn || '') : timeColumn} onChange={(event) => { setTimeColumn(event.target.value); clearSuggestion(); }}>
                <option value="">Each reading of the total</option>
                {ctx.preview.headers.map((header) => <option key={header} value={header}>{header}</option>)}
              </select>
            </label>
            <label className="setup-field">Chart
              <select aria-label="Chart" value={asChart(proposal?.chart || chart)} onChange={(event) => { setChart(asChart(event.target.value)); clearSuggestion(); }}>
                <option value="line">Line</option>
                <option value="column">Columns</option>
                <option value="area">Area</option>
              </select>
            </label>
            <label className="setup-field">Aggregate
              <select aria-label="Aggregate" value={proposal?.aggregate || aggregate} onChange={(event) => { setAggregate(event.target.value); clearSuggestion(); }}>
                <option value="sum">Sum</option>
                <option value="count">Count</option>
                <option value="latest">Latest</option>
                <option value="min">Min</option>
                <option value="max">Max</option>
              </select>
            </label>
          </div>
          {proposal ? (
            <div className="setup-proposal" role="status">
              {disclosure ? <p className="setup-reason">{disclosure}</p> : null}
              <p className="setup-reason">
                {proposal.source === 'heuristic' ? 'Suggested on this machine. ' : ''}
                {proposal.reason}
              </p>
              <div className="setup-actions">
                <Button tone="primary" onClick={() => acceptSuggestion(ctx, proposal)}>Accept</Button>
              </div>
            </div>
          ) : (
            <Button
              tone="primary"
              className="setup-continue"
              onClick={() => ctx.toConfirm()}
              disabled={ctx.busy || !ctx.ready}
            >
              Continue
            </Button>
          )}
        </>
      )}
      confirmBody={confirmBody}
    />
  );
}
