// The tracker setup sheet: the shared instance walk (open a workbook,
// choose columns and rows, confirm) with the tracker's own slots, the
// suggest proposal and the endpoint's evaluate check among them. The
// walk owns the guarded requests, the picker recovery and the
// outside-workspace acceptance; this file only adapts the dashboard's
// API envelope onto the walk's answers.
import { useEffect, useState } from 'react';
import { getJson, postFile, postJson, type ApiResult } from '../api';
import Button from '../components/Button';
import InstanceWalk, {
  type ChooseCtx,
  type ConfirmCtx,
  type InstanceWalkRequests,
  type OpenWay,
  type WalkOpen,
  type WalkSave,
} from '../components/InstanceWalk';
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

interface Review {
  verdict: 'ok' | 'adjust' | 'unchecked';
  message: string;
  recommendation: Proposal | null;
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
  const [headersOnly, setHeadersOnly] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [suggested, setSuggested] = useState(false);

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

  const base = `/api/plugins/${encodeURIComponent(pluginId)}/instances/${encodeURIComponent(instanceId)}`;
  const pickUrl = `${base}/pick`;
  const suggestUrl = `${base}/suggest`;
  const evaluateUrl = `${base}/evaluate`;
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
            aggregate: 'sum',
            unit,
            rows: choice.picked,
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
   * Ask for a suggestion and adopt its columns and rows as a proposal
   * awaiting Accept or Adjust; the request runs under the walk's guard,
   * so an unreachable server fills the error slot and unblocks.
   */
  async function suggest(ctx: ChooseCtx) {
    await ctx.ask(async () => {
      let res;
      try {
        res = await postJson(suggestUrl, { headersOnly });
      } catch {
        return { ok: false, message: 'The dashboard could not reach its own server; nothing was suggested.' };
      }
      if (res.status === 401) { onExpired(); return { ok: false }; }
      const data = res.data as { proposal?: Proposal | null; error?: string };
      if (!res.ok || !data.proposal) {
        return { ok: false, message: data.error || 'No suggestion came back.' };
      }
      setProposal(data.proposal);
      setSuggested(true);
      ctx.adopt({
        labelColumn: data.proposal.labelColumn,
        valueColumn: data.proposal.valueColumn,
        picked: data.proposal.rows ?? [],
      });
      return { ok: true };
    });
  }

  /** Keep the suggestion as it stands and move to the naming step. */
  function acceptSuggestion(ctx: ChooseCtx) {
    setProposal(null);
    setSuggested(true);
    ctx.toConfirm();
  }

  // Continue is one press: the endpoint gets one look at the chosen
  // columns and rows. A missing endpoint, a bad response, or a verdict
  // with nothing to change lets the choice straight through; only a real
  // recommendation holds the sheet open.
  /**
   * Run the one check on the chosen columns and rows before the naming step.
   *
   * The sheet stays open only for a recommendation with something to change; an
   * unreachable endpoint, a refused answer or a verdict that offers nothing
   * lets the choice through to the naming step.
   */
  async function checkChoice(ctx: ChooseCtx) {
    const res = await ctx.try(() => postJson(evaluateUrl, {
      tracking: {
        labelColumn: ctx.choice.labelColumn,
        valueColumn: ctx.choice.valueColumn,
        aggregate: 'sum',
        rows: ctx.choice.picked,
      },
    }));
    if (res === undefined) { ctx.toConfirm(); return; }
    if (res.status === 401) { onExpired(); return; }
    if (!res.ok) { ctx.toConfirm(); return; }
    const data = res.data as { verdict?: string; message?: string; recommendation?: Proposal | null };
    const verdict = data.verdict === 'adjust' || data.verdict === 'unchecked' ? data.verdict : 'ok';
    const next: Review = {
      verdict,
      message: data.message || 'The check came back without a note.',
      recommendation: data.recommendation ?? null,
    };
    setReview(next);
    if (!next.recommendation) ctx.toConfirm();
  }

  /**
   * Adopt the checker's recommendation, keeping the picked rows unless it names
   * its own, and move to the naming step.
   */
  function useRecommendation(ctx: ChooseCtx, recommendation: Proposal) {
    ctx.adopt({
      labelColumn: recommendation.labelColumn,
      valueColumn: recommendation.valueColumn,
      picked: recommendation.rows && recommendation.rows.length > 0
        ? recommendation.rows
        : ctx.choice.picked,
    });
    setReview(null);
    setProposal(null);
    setSuggested(true);
    ctx.toConfirm();
  }

  /** Keep the chosen columns and rows, dismiss the review and move on. */
  function keepMine(ctx: ChooseCtx) {
    setReview(null);
    ctx.toConfirm();
  }

  /** The naming step's body, from the choice the walk carries. */
  function confirmBody(ctx: ConfirmCtx) {
    return (
      <>
        <p className="setup-summary mono">{ctx.columns.valueColumn} by {ctx.columns.labelColumn} · {ctx.columns.picked.length} rows</p>
        {review ? (
          <p className="setup-check-note" data-testid="evaluate-note">
            <span className={`verdict-tag is-${review.verdict}`}>
              {review.verdict === 'unchecked' ? 'CHECK SKIPPED' : review.verdict === 'adjust' ? 'KEPT YOUR CHOICE' : 'LOOKS RIGHT'}
            </span>{' '}
            {review.message}
          </p>
        ) : null}
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
            <div><dt>You pick</dt><dd>One value column, a row label and the rows to count</dd></div>
            <div><dt>Shows</dt><dd>The total, its change since the last reading and a sparkline</dd></div>
          </dl>
        </>
      )}
      openTrail={<div className="setup-open-wire"><WireChart bars={8} /></div>}
      onChoiceChanged={() => {
        setProposal(null);
        setReview(null);
        setSuggested(false);
      }}
      chooseFooter={(ctx) => (
        <>
          <div className="setup-suggest">
            <p data-testid="suggest-disclosure">
              {headersOnly
                ? `Sends the headers ${ctx.preview.headers.join(', ')}. No cell values and no file path leave this machine.`
                : `Sends the headers ${ctx.preview.headers.join(', ')} and ${Math.min(ctx.preview.rows.length, 5)} rows. The file path stays on this machine.`}
            </p>
            <Button tone="secondary" onClick={() => void suggest(ctx)} disabled={ctx.busy}>Suggest what to track</Button>
          </div>
          {proposal ? (
            <div className="setup-proposal" role="status">
              <p className="setup-reason">
                {proposal.source === 'heuristic' ? 'Suggested on this machine. ' : ''}
                {proposal.reason}
              </p>
              <div className="setup-actions">
                <Button tone="primary" onClick={() => acceptSuggestion(ctx)}>Accept</Button>
                <Button tone="secondary" onClick={() => setProposal(null)}>Adjust</Button>
              </div>
            </div>
          ) : review?.recommendation ? (
            <div className="setup-proposal setup-review" role="status">
              <p className="setup-verdict" data-testid="evaluate-verdict">
                <span className={`verdict-tag is-${review.verdict}`}>SUGGESTION</span>
                {review.message}
              </p>
              <p className="setup-reason">
                <strong>{review.recommendation.valueColumn}</strong> by <strong>{review.recommendation.labelColumn}</strong>
                {review.recommendation.rows && review.recommendation.rows.length > 0
                  ? ` · ${review.recommendation.rows.length} rows` : ''}
                {review.recommendation.reason ? ` (${review.recommendation.reason})` : ''}
              </p>
              <div className="setup-actions">
                <Button tone="primary" onClick={() => useRecommendation(ctx, review.recommendation as Proposal)}>Use this instead</Button>
                <Button tone="secondary" onClick={() => keepMine(ctx)}>Keep mine</Button>
              </div>
            </div>
          ) : (
            <>
              <Button
                tone="primary"
                className="setup-continue"
                onClick={() => void checkChoice(ctx)}
                disabled={ctx.busy || !ctx.ready}
              >
                {ctx.busy ? 'Checking…' : 'Continue'}
              </Button>
              <p className="setup-check-note">
                One check runs here: the headers and up to 5 row values go to the company endpoint. The file path
                stays on this machine. A missing endpoint skips the check; your choice still works.
              </p>
            </>
          )}
        </>
      )}
      confirmBody={confirmBody}
    />
  );
}
