// The Memory page: the loop a knowledge point goes through, laid out as
// the user works it. Capture proposes facts from the Assistant and
// Research; the review queue decides what is saved; the stored
// knowledge shows each fact with where it came from and what it
// changed; removal says what else changes before anything is written,
// and can be undone for a short window.
//
// The page title, the explanation that leads the page, the Forget
// everything control and the Maintenance disclosure are the server's,
// rendered around this island (ticket #283). The graph is one of those
// maintenance tools, on its own page at /memory/graph.
//
// Reads GET /api/memory/loop and writes only through the server's own
// routes: /settings/toggle, /memory/add, /memory/<id>/edit, the inbox
// card routes for review, /api/memory/remove(/preview),
// /api/memory/undo and /api/memory/facts/<id>/keep.
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react';
import { getJson, postJson } from '../../api';
import { AGENT_NAME } from '../../face/name';
import { SkeletonLine, WaitButton, WaitLine, useBusy, useWaitPhase } from '../feedback';
import {
  CHANNEL_HINT, channelList, count, LIST_CAP, methodLabel, observationWriter, removeLabel, removedSummary, stamp, TARGET_NOUN,
} from './copy';
import type {
  Candidate, EntityRow, FactRow, LoopState, ObservationRow, RemovalDone, RemovalPlan, SourceRow, TargetType,
} from './types';

type Load =
  | { state: 'loading' }
  | { state: 'ready'; data: LoopState }
  | { state: 'failed'; message: string };

type Outcome = { ok: true; data: unknown } | { ok: false; message: string };
type Ack = { ok: boolean; message?: string };

type Tab = 'facts' | 'entities' | 'sources' | 'observations';

interface Undo {
  token: string;
  expiresTs: number;
  windowS: number;
  summary: string;
}

export interface MemoryLoopProps {
  endpoint?: string;
  // Background captures land between page actions; the page re-reads
  // while it is visible. Tests pass 0 to turn the poll off.
  pollMs?: number;
}

/**
 * Return the message to show for a failed response.
 *
 * A 401 means the session's link expired and gets its own sentence; otherwise
 * the server's error or cause is appended to fallback, so the reason a write
 * failed is not lost.
 */
async function errorOf(res: { status: number; data: unknown }, fallback: string): Promise<string> {
  if (res.status === 401) {
    return `Your session ended. Open ${AGENT_NAME} from its shortcut to get a fresh link.`;
  }
  const error = (res.data as { error?: string; cause?: string }).error ?? (res.data as { cause: string }).cause;
  return error ? `${fallback} ${error}` : fallback;
}

/**
 * The Memory page: capture, review, stored knowledge, and removal.
 *
 * Reads the loop endpoint on mount and, while the tab is visible, every pollMs;
 * 0 turns the poll off. Writes go through the server's own routes.
 */
export default function MemoryLoop({ endpoint = '/api/memory/loop', pollMs = 8000 }: MemoryLoopProps) {
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const loadRef = useRef<Load>({ state: 'loading' });
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [plan, setPlan] = useState<RemovalPlan | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [undo, setUndo] = useState<Undo | null>(null);
  const [removedCount, setRemovedCount] = useState(0);
  const [tab, setTab] = useState<Tab>('facts');
  const [filter, setFilter] = useState('');

  const refresh = useCallback(async () => {
    const initial = loadRef.current.state !== 'ready';
    if (!initial) setRefreshing(true);
    try {
      const res = await getJson(endpoint);
      if (res.ok) {
        const next: Load = { state: 'ready', data: res.data as LoopState };
        loadRef.current = next;
        setLoad(next);
        setRefreshError(null);
      } else {
        const message = await errorOf(res, 'Memory could not be read.');
        if (initial) {
          const next: Load = { state: 'failed', message };
          loadRef.current = next;
          setLoad(next);
        } else {
          setRefreshError(`${message} You are looking at the previous content.`);
        }
      }
    } catch {
      if (initial) {
        const next: Load = { state: 'failed', message: 'The page could not reach its own server.' };
        loadRef.current = next;
        setLoad(next);
      } else {
        setRefreshError('The page could not reach its own server. You are looking at the previous content.');
      }
    } finally {
      setRefreshing(false);
    }
  }, [endpoint]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!pollMs) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refresh();
    }, pollMs);
    return () => window.clearInterval(timer);
  }, [pollMs, refresh]);

  /** One write, with its failure message kept for the place that asks. */
  const actOutcome = useCallback(async (url: string, body: unknown, failure: string): Promise<Outcome> => {
    try {
      const res = await postJson(url, body);
      if (res.ok) return { ok: true, data: res.data };
      return { ok: false, message: await errorOf(res, failure) };
    } catch {
      return { ok: false, message: 'The page could not reach its own server; nothing changed.' };
    }
  }, []);

  const askRemoval = useCallback(async (type: TargetType, id: number): Promise<Ack> => {
    setPreviewing(true);
    const outcome = await actOutcome('/api/memory/remove/preview', { target: { type, id } }, 'That could not be checked.');
    setPreviewing(false);
    if (!outcome.ok) return { ok: false, message: outcome.message };
    setPlan((outcome.data as { plan: RemovalPlan }).plan);
    return { ok: true };
  }, [actOutcome]);

  const confirmRemoval = useCallback(async (): Promise<Ack> => {
    if (!plan) return { ok: false, message: 'Nothing was removed.' };
    const outcome = await actOutcome('/api/memory/remove', { target: { type: plan.target.type, id: plan.target.id } }, 'Nothing was removed.');
    if (!outcome.ok) return { ok: false, message: outcome.message };
    setPlan(null);
    const answer = outcome.data as { removed: RemovalDone; undo: { token: string; expiresTs: number } };
    const ready = loadRef.current;
    setUndo({
      token: answer.undo.token, expiresTs: answer.undo.expiresTs,
      windowS: ready.state === 'ready' ? ready.data.undoWindowS : 30, summary: removedSummary(answer.removed),
    });
    setRemovedCount((n) => n + (answer.removed.facts.length || 1));
    await refresh();
    return { ok: true };
  }, [actOutcome, plan, refresh]);

  const runUndo = useCallback(async (): Promise<Ack> => {
    if (!undo) return { ok: false, message: 'The removal could not be undone.' };
    const outcome = await actOutcome('/api/memory/undo', { token: undo.token }, 'The removal could not be undone.');
    if (!outcome.ok) return { ok: false, message: outcome.message };
    setUndo(null);
    setRemovedCount(0);
    setNotice('Removal undone. Everything it touched is back.');
    await refresh();
    return { ok: true };
  }, [actOutcome, undo, refresh]);

  const closePlan = useCallback(() => setPlan(null), []);
  const dropUndo = useCallback(() => setUndo(null), []);

  if (load.state === 'loading') {
    return <LoopLoading />;
  }
  if (load.state === 'failed') {
    return (
      <div className="ml">
        <p className="ml-alert" role="alert">{load.message}</p>
      </div>
    );
  }
  const data = load.data;

  return (
    <div className={`ml${refreshing ? ' ml-is-refreshing' : ''}`} aria-busy={refreshing || undefined}>
      <Header data={data} />
      <Flow data={data} removedCount={removedCount} />
      <RefreshLine active={refreshing} error={refreshError} onRetry={() => { setRefreshError(null); void refresh(); }} />
      {notice && (
        <p className="ml-notice" role="status">
          {notice}
          <button type="button" className="ml-text-btn" onClick={() => setNotice(null)}>Dismiss</button>
        </p>
      )}
      <div className="ml-grid">
        <Review data={data} actOutcome={actOutcome} onChanged={() => refresh()} />
        <div className="ml-side">
          <CaptureSettings data={data} actOutcome={actOutcome} onChanged={() => refresh()} />
          <AddFact actOutcome={actOutcome} onChanged={() => refresh()} />
        </div>
        <Knowledge
          data={data}
          tab={tab}
          onTab={setTab}
          filter={filter}
          onFilter={setFilter}
          onRemove={askRemoval}
          onKeep={async (id) => {
            const outcome = await actOutcome(`/api/memory/facts/${id}/keep`, {}, 'That fact could not be kept.');
            if (!outcome.ok) return outcome;
            await refresh();
            return { ok: true };
          }}
          onEdit={async (id, text) => {
            const outcome = await actOutcome(`/memory/${id}/edit`, { text }, 'The edit was not saved.');
            if (!outcome.ok) return outcome;
            const merged = Boolean((outcome.data as { mergedIntoExisting?: boolean }).mergedIntoExisting);
            if (merged) setNotice('That edit matched a fact already saved with the same words, so the two were merged into one.');
            await refresh();
            return { ok: true, merged };
          }}
          onReflect={async () => {
            const outcome = await actOutcome('/memory/reflect', {}, 'Observations could not be derived.');
            if (!outcome.ok) return outcome;
            await refresh();
            return { ok: true, data: outcome.data };
          }}
        />
      </div>
      {previewing && <RemovePreviewSkeleton />}
      {plan && <RemoveDialog plan={plan} onCancel={closePlan} onConfirm={confirmRemoval} />}
      {undo && <UndoBar undo={undo} onUndo={runUndo} onExpire={dropUndo} />}
    </div>
  );
}

type ActOutcome = (url: string, body: unknown, failure: string) => Promise<Outcome>;

/** One place for the quiet refresh line and its failure, never a wipe. */
function RefreshLine({ active, error, onRetry }: { active: boolean; error: string | null; onRetry: () => void }) {
  const busy = useBusy(active);
  if (error) {
    return (
      <p className="ml-refresh-line" role="alert">
        {error}
        <button type="button" className="ml-text-btn" onClick={onRetry}>Try again</button>
      </p>
    );
  }
  if (!busy) return null;
  return (
    <p className="ml-refresh-line" role="status">
      <span className="mem-busy-dot" aria-hidden="true" />
      Refreshing memory…
    </p>
  );
}

/** The first wait, shaped like the page it will become. */
function LoopLoading() {
  const phase = useWaitPhase(true);
  return (
    <div className={`ml${phase === 'idle' ? '' : ' ml-skeleton'}`} aria-busy="true">
      {phase !== 'idle' && (
        <>
          <p className="ml-feedback-phase" role="status">Reading your memory…</p>
          <div className="ml-head" aria-hidden="true"><SkeletonLine className="mem-skeleton-title" /></div>
          <div className="ml-flow" aria-hidden="true">
            {[0, 1, 2, 3].map((index) => (
              <div className="ml-step" key={index}>
                <div className="ml-step-link">
                  <SkeletonLine className="mem-skeleton-short" />
                  <SkeletonLine className="mem-skeleton-block" />
                  <SkeletonLine />
                  <SkeletonLine className="mem-skeleton-short" />
                </div>
              </div>
            ))}
          </div>
          <div className="ml-grid" aria-hidden="true">
            <section className="ml-tile ml-span-8">
              <SkeletonLine className="mem-skeleton-title" />
              <SkeletonLine />
              <SkeletonLine />
            </section>
            <div className="ml-side">
              <section className="ml-tile">
                <SkeletonLine className="mem-skeleton-short" />
                <SkeletonLine />
                <SkeletonLine />
              </section>
              <section className="ml-tile">
                <SkeletonLine className="mem-skeleton-short" />
                <SkeletonLine className="mem-skeleton-block" />
              </section>
            </div>
            <section className="ml-tile ml-span-12">
              <SkeletonLine className="mem-skeleton-title" />
              <div className="ml-rows">
                {[0, 1].map((index) => (
                  <div className="ml-row" key={index}>
                    <div className="ml-row-main">
                      <SkeletonLine />
                      <SkeletonLine className="mem-skeleton-short" />
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * The page's state line. The page title is the server's, rendered above
 * the explanation that leads the page (ticket #283), so the island opens
 * with how much is remembered and one line of capture state.
 */
function Header({ data }: { data: LoopState }) {
  const on = data.capture.channels.filter((c) => c.on).map((c) => c.label);
  const capture = !data.capture.enabled || on.length === 0
    ? 'Learning is off: facts arrive only when you type or approve them.'
    : `Learning from ${channelList(on)}. ${data.capture.autoApprove ? 'New facts are saved automatically.' : 'New facts wait for your review.'}`;
  return (
    <header className="ml-head">
      <p className="ml-sub">
        {count(data.counts.standing, 'fact')} the assistant can recall, across {count(data.counts.entities, 'entity', 'entities')}. {capture}
      </p>
    </header>
  );
}

/**
 * The four-step strip: learn, store, process, remove.
 *
 * Each step links to the section that works it and reports state rather than
 * instructions: the last capture, the standing counts, the window a removal can
 * still be undone in.
 */
function Flow({ data, removedCount }: { data: LoopState; removedCount: number }) {
  const last = data.lastCapture;
  const lastLine = last
    ? `Last from ${last.channelLabel} at ${stamp(last.ts)}: ${count(last.found, 'fact')} found, ${last.staged} to review, ${last.stored} saved.`
    : 'Nothing learned since the app started.';
  const steps: { id: string; tag: string; figure: number; unit: string; line: string; href: string; mark?: string }[] = [
    {
      id: 'capture', tag: 'Learn', figure: data.counts.waiting, unit: 'waiting for review',
      line: lastLine, href: '#ml-review', mark: methodLabel(data.extractor.mode),
    },
    {
      id: 'store', tag: 'Store', figure: data.counts.standing, unit: data.counts.standing === 1 ? 'fact in recall' : 'facts in recall',
      line: data.counts.replaced
        ? `${count(data.counts.replaced, 'older fact')} replaced by a newer value, kept so you can check.`
        : `${count(data.counts.sources, 'excerpt')} kept as provenance.`,
      href: '#ml-knowledge',
    },
    {
      id: 'process', tag: 'Process', figure: data.counts.observations, unit: data.counts.observations === 1 ? 'observation' : 'observations',
      line: data.counts.flagged
        ? `${count(data.counts.flagged, 'observation')} lost a cited fact and needs a look.`
        : 'One per entity that two or more facts mention, rebuilt when those facts change.',
      href: '#ml-knowledge',
    },
    {
      id: 'remove', tag: 'Remove', figure: removedCount, unit: 'removed this visit',
      line: `Every removal shows what else changes first, and can be undone for ${data.undoWindowS} seconds.`,
      href: '#ml-knowledge',
    },
  ];
  return (
    <ol className="ml-flow" aria-label="How memory is built">
      {steps.map((step, index) => (
        <li key={step.id} className={`ml-step ml-step-${step.id}`}>
          <a href={step.href} className="ml-step-link">
            <span className="ml-step-top">
              <span className="ml-step-index">{String(index + 1).padStart(2, '0')}</span>
              <span className="ml-tag">{step.tag}</span>
              {step.mark && <span className="ml-chip-quiet">{step.mark}</span>}
            </span>
            <span className="ml-figure">{step.figure}</span>
            <span className="ml-step-unit" title={step.unit}>{step.unit}</span>
            <span className="ml-step-line">{step.line}</span>
          </a>
        </li>
      ))}
    </ol>
  );
}

/**
 * The review queue, with "Approve all" once there is more than one candidate.
 *
 * Each decision holds its own button, one at a time; approve-all walks the
 * queue and reports the honest count where the queue is.
 */
function Review({ data, actOutcome, onChanged }: { data: LoopState; actOutcome: ActOutcome; onChanged: () => void }) {
  const [pending, setPending] = useState<{ cardId: string; decision: 'accept' | 'dismiss' } | null>(null);
  const [all, setAll] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0, failed: 0 });
  const [error, setError] = useState<{ cardId: string; decision: 'accept' | 'dismiss'; message: string } | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const blocked = pending !== null || all;

  /**
   * Approve or reject one candidate, saving an edited text first.
   *
   * A failed edit or decision stays on the card, with what was typed kept;
   * the next attempt starts from the same text.
   */
  const decide = async (candidate: Candidate, decision: 'accept' | 'dismiss', text?: string) => {
    if (blocked) return;
    setPending({ cardId: candidate.cardId, decision });
    setError(null);
    setResult(null);
    if (decision === 'accept' && text !== undefined && text.trim() && text.trim() !== candidate.text) {
      const edited = await actOutcome(`/inbox/cards/${candidate.cardId}/edit`, { draft: text.trim() }, 'The edit was not saved.');
      if (!edited.ok) {
        setPending(null);
        setError({ cardId: candidate.cardId, decision, message: edited.message });
        return;
      }
    }
    const saved = await actOutcome(`/inbox/cards/${candidate.cardId}/${decision}`, {},
      decision === 'accept' ? 'It was not saved.' : 'It was not rejected.');
    setPending(null);
    if (!saved.ok) {
      setError({ cardId: candidate.cardId, decision, message: saved.message });
      return;
    }
    setResult(decision === 'accept' ? 'Saved. The fact is now in stored knowledge.' : 'Rejected. The candidate was dismissed.');
    onChanged();
  };
  /** Accept every candidate in order, counting the ones that fail. */
  const approveAll = async () => {
    if (blocked) return;
    const total = data.candidates.length;
    setAll(true);
    setProgress({ done: 0, total, failed: 0 });
    setError(null);
    setResult(null);
    let failed = 0;
    let processed = 0;
    for (const candidate of data.candidates) {
      const saved = await actOutcome(`/inbox/cards/${candidate.cardId}/accept`, {}, 'One candidate was not saved.');
      if (!saved.ok) failed += 1;
      processed += 1;
      setProgress({ done: processed, total, failed });
    }
    setAll(false);
    setResult(`Approved ${total - failed} of ${total}. ${failed ? `${failed} could not be saved.` : 'All were saved.'}`);
    onChanged();
  };
  return (
    <section className="ml-tile ml-span-8 ml-review" id="ml-review" aria-labelledby="ml-review-h">
      <div className="ml-tile-head">
        <h2 className="ml-tag" id="ml-review-h">Review</h2>
        <span className="ml-tile-count">{count(data.candidates.length, 'candidate')}</span>
        {data.candidates.length > 1 && (
          <WaitButton className="ml-btn" active={all} disabled={pending !== null} idle="Approve all"
            working={`Approving ${progress.done} of ${progress.total}...`} onClick={approveAll} />
        )}
      </div>
      {result && <p className="ml-feedback-result" role="status">{result}</p>}
      {all && (
        <WaitLine active working={`Approving ${progress.done} of ${progress.total} candidates…`}
          slow="Still approving candidates… This is taking longer than usual. You can leave this page."
          className="ml-feedback-phase" />
      )}
      {data.candidates.length === 0 ? (
        <div className="ml-empty">
          <p className="ml-empty-title">Nothing to review</p>
          <p>
            {data.capture.enabled && !data.capture.autoApprove
              ? 'When you tell the Assistant or Research something worth keeping, the facts it finds wait here before they are saved.'
              : data.capture.autoApprove
                ? 'Facts are saved as soon as they are found. Turn on review in Learning settings to check them first.'
                : 'Learning is off. Turn it on in Learning settings, or type a fact yourself.'}
          </p>
        </div>
      ) : (
        <ul className="ml-cands">
          {data.candidates.map((candidate) => (
            <CandidateItem key={candidate.cardId} candidate={candidate}
              pending={pending?.cardId === candidate.cardId ? pending.decision : null}
              blocked={blocked}
              error={error?.cardId === candidate.cardId ? error : null}
              onDecide={decide} />
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * One review card: what was found, where it came from, and its actions.
 *
 * Only facts can be edited, and an edited text travels with the approval. The
 * excerpt and the cited facts open in place.
 */
function CandidateItem({ candidate, pending, blocked, error, onDecide }: {
  candidate: Candidate;
  pending: 'accept' | 'dismiss' | null;
  blocked: boolean;
  error: { decision: 'accept' | 'dismiss'; message: string } | null;
  onDecide: (candidate: Candidate, decision: 'accept' | 'dismiss', text?: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(candidate.text);
  const id = `ml-cand-${candidate.cardId}`;
  const edited = editing ? text : undefined;
  return (
    <li className="ml-cand" aria-labelledby={`${id}-text`}>
      <div className="ml-cand-meta">
        <span className="ml-chip">{candidate.type === 'observation' ? 'Observation' : candidate.channelLabel}</span>
        <span className="ml-chip-quiet">{methodLabel(candidate.method)}</span>
        <time className="ml-mono">{stamp(candidate.createdTs)}</time>
      </div>
      {editing ? (
        <div className="ml-edit">
          <label className="ml-sr" htmlFor={`${id}-input`}>Edit before saving</label>
          <textarea id={`${id}-input`} name="candidate" autoComplete="off" value={text} rows={2} onChange={(e) => setText(e.target.value)} />
        </div>
      ) : (
        <p className="ml-cand-text" id={`${id}-text`}>{candidate.text}</p>
      )}
      {candidate.entities.length > 0 && (
        <p className="ml-chips" aria-label="Mentions">
          {candidate.entities.map((e) => <span key={e.name} className="ml-entity">{e.name}</span>)}
        </p>
      )}
      {candidate.excerpt && (
        <details className="ml-excerpt">
          <summary>{candidate.channel === 'workbook' ? 'From the workbook change' : 'From what was said'}</summary>
          <blockquote>{candidate.excerpt.text}</blockquote>
        </details>
      )}
      {candidate.cites && candidate.cites.length > 0 && (
        <details className="ml-excerpt">
          <summary>Cites {count(candidate.cites.length, 'fact')}</summary>
          <ul>{candidate.cites.map((c) => <li key={c.id}>{c.text}</li>)}</ul>
        </details>
      )}
      <div className="ml-actions">
        <WaitButton className="ml-btn ml-btn-primary" active={pending === 'accept'} disabled={blocked}
          idle={editing ? 'Save edited' : 'Approve'} working="Saving..."
          onClick={() => onDecide(candidate, 'accept', editing ? text : undefined)} />
        {!editing && candidate.type === 'fact' && (
          <button type="button" className="ml-btn" disabled={blocked} onClick={() => setEditing(true)}>Edit</button>
        )}
        {editing && (
          <button type="button" className="ml-btn" disabled={pending !== null}
            onClick={() => { setEditing(false); setText(candidate.text); }}>Cancel edit</button>
        )}
        <WaitButton className="ml-btn" active={pending === 'dismiss'} disabled={blocked}
          idle="Reject" working="Rejecting..." onClick={() => onDecide(candidate, 'dismiss')} />
      </div>
      {pending && (
        <WaitLine active working={pending === 'dismiss' ? 'Rejecting this candidate…' : 'Saving this fact…'}
          slow="Still saving… This is taking longer than usual. You can leave this page."
          className="ml-feedback-phase" />
      )}
      {error && (
        <p className="ml-feedback-error" role="alert">
          {error.message}
          <button type="button" className="ml-text-btn"
            onClick={() => onDecide(candidate, error.decision, edited)}>Try again</button>
        </p>
      )}
    </li>
  );
}

/**
 * A labelled on/off row: the label and optional hint, then the switch.
 *
 * The visible label is the button's accessible name; disabled marks the row as
 * well as the button. A pending switch says so at 100 ms and names the wait
 * under the row from one second.
 */
function Switch({ id, label, hint, on, disabled, pending = false, onToggle }: {
  id: string; label: string; hint?: string; on: boolean; disabled?: boolean; pending?: boolean; onToggle: () => void;
}) {
  const busy = useBusy(pending);
  return (
    <div className={`ml-switch-row${disabled ? ' is-disabled' : ''}`}>
      <span className="ml-switch-label" id={`${id}-label`}>
        {label}
        {hint && <span className="ml-switch-hint">{hint}</span>}
      </span>
      <button type="button" role="switch" aria-checked={on} aria-labelledby={`${id}-label`}
        className="ml-switch" disabled={disabled || pending} aria-busy={busy || undefined} onClick={onToggle}>
        <span className="ml-switch-knob" />
      </button>
      {pending && (
        <WaitLine active working={`Saving ${label}…`}
          slow="Still saving this setting… This is taking longer than usual. You can leave this page."
          className="ml-feedback-phase ml-switch-wait" />
      )}
    </div>
  );
}

/**
 * Learning settings: what is read from, and whether a found fact waits.
 *
 * Each switch writes one setting and re-reads the page. One setting at a
 * time: the switch holds until the store answers, and a refusal stays in
 * the tile with the switch unchanged.
 */
function CaptureSettings({ data, actOutcome, onChanged }: { data: LoopState; actOutcome: ActOutcome; onChanged: () => void }) {
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [pendingAuto, setPendingAuto] = useState<'ask' | 'auto' | null>(null);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const askBusy = useBusy(pendingKey === 'memory_auto_approve' && pendingAuto === 'ask');
  const autoBusy = useBusy(pendingKey === 'memory_auto_approve' && pendingAuto === 'auto');
  /** Flip one setting, then re-read so the switches show the stored value. */
  const toggle = async (key: string) => {
    if (pendingKey) return;
    setPendingKey(key);
    setError(null);
    setResult(null);
    const outcome = await actOutcome('/settings/toggle', { key }, 'The setting was not changed.');
    setPendingKey(null);
    setPendingAuto(null);
    if (!outcome.ok) {
      setError({ key, message: outcome.message });
      return;
    }
    setResult('Setting saved.');
    onChanged();
  };
  /** Save automatic capture on or off; a second choice waits for the first. */
  const chooseAuto = (auto: boolean) => {
    if (pendingKey) return;
    setPendingAuto(auto ? 'auto' : 'ask');
    void toggle('memory_auto_approve');
  };
  const capture = data.capture;
  return (
    <section className="ml-tile" aria-labelledby="ml-capture-h">
      <div className="ml-tile-head">
        <h2 className="ml-tag" id="ml-capture-h">Learning settings</h2>
      </div>
      <Switch id="ml-sw-capture" label="Learn facts as you work" on={capture.enabled}
        pending={pendingKey === 'memory_capture'}
        disabled={pendingKey !== null && pendingKey !== 'memory_capture'}
        onToggle={() => toggle('memory_capture')} />
      <fieldset className="ml-fieldset" disabled={!capture.enabled || pendingKey !== null}>
        <legend>Read from</legend>
        {capture.channels.map((channel) => (
          <Switch key={channel.id} id={`ml-sw-${channel.id}`} label={channel.label}
            hint={CHANNEL_HINT[channel.id]}
            on={channel.on} disabled={!capture.enabled}
            pending={pendingKey === channel.setting}
            onToggle={() => toggle(channel.setting)} />
        ))}
      </fieldset>
      <fieldset className="ml-fieldset" disabled={!capture.enabled || pendingKey !== null}>
        <legend>When a fact is found</legend>
        <div className="ml-segment" role="radiogroup" aria-label="When a fact is found">
          <button type="button" role="radio" aria-checked={!capture.autoApprove}
            aria-busy={askBusy || undefined}
            title="Ask me first"
            disabled={pendingKey !== null}
            onClick={() => capture.autoApprove && chooseAuto(false)}>Ask me first</button>
          <button type="button" role="radio" aria-checked={capture.autoApprove}
            aria-busy={autoBusy || undefined}
            title="Save automatically"
            disabled={pendingKey !== null}
            onClick={() => !capture.autoApprove && chooseAuto(true)}>Save automatically</button>
        </div>
        {pendingKey === 'memory_auto_approve' && (
          <WaitLine active working={pendingAuto === 'auto' ? 'Saving facts as they are found…' : 'Saving when facts are reviewed…'}
            slow={pendingAuto === 'auto'
              ? 'Still saving facts as they are found… This is taking longer than usual. You can leave this page.'
              : 'Still saving this setting… This is taking longer than usual. You can leave this page.'}
            className="ml-feedback-phase" />
        )}
      </fieldset>
      <p className="ml-note">{data.extractor.detail}</p>
      {data.lastCapture?.cause && (
        <p className="ml-note">Last error: {data.lastCapture.cause}</p>
      )}
      {result && <p className="ml-feedback-result" role="status">{result}</p>}
      {error && (
        <p className="ml-feedback-error" role="alert">
          {error.message}
          <button type="button" className="ml-text-btn" onClick={() => toggle(error.key)}>Try again</button>
        </p>
      )}
    </section>
  );
}

/**
 * The "add a fact" form: one typed sentence, saved as written.
 *
 * An empty submit is refused in place and focuses the field; a failed save
 * keeps what was typed and says so under the box; a saved fact clears the
 * field and re-reads the page.
 */
function AddFact({ actOutcome, onChanged }: { actOutcome: ActOutcome; onChanged: () => void }) {
  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  /** Save the typed sentence, or mark the field when it is blank. */
  const submit = async (event: { preventDefault: () => void }) => {
    event.preventDefault();
    if (saving) return;
    if (!text.trim()) {
      setEmpty(true);
      inputRef.current?.focus();
      return;
    }
    setSaving(true);
    setError(null);
    setResult(null);
    const outcome = await actOutcome('/memory/add', { text: text.trim() }, 'The fact was not saved.');
    setSaving(false);
    if (!outcome.ok) {
      setError(outcome.message);
      return;
    }
    setText('');
    setResult('Saved. The fact is now in stored knowledge.');
    onChanged();
  };
  return (
    <section className="ml-tile" aria-labelledby="ml-add-h">
      <div className="ml-tile-head"><h2 className="ml-tag" id="ml-add-h">Add a fact</h2></div>
      <form className="ml-add" onSubmit={submit}>
        <label className="ml-sr" htmlFor="ml-add-input">Fact</label>
        <textarea id="ml-add-input" name="fact" ref={inputRef} rows={2} value={text} autoComplete="off"
          placeholder="The Acme renewal is due December 15…" aria-invalid={empty || undefined}
          aria-describedby={empty ? 'ml-add-error' : undefined}
          onChange={(e) => { setText(e.target.value); setEmpty(false); setError(null); }} />
        {empty && <p className="ml-field-error" id="ml-add-error">Type the fact first, in one sentence.</p>}
        <WaitButton className="ml-btn ml-btn-primary" type="submit" active={saving}
          idle="Save fact" working="Saving..." />
        {error && (
          <p className="ml-feedback-error" role="alert">
            {error}
            <button type="button" className="ml-text-btn" onClick={submit}>Try again</button>
          </p>
        )}
        {result && <p className="ml-feedback-result" role="status">{result}</p>}
        {saving && (
          <WaitLine active working="Saving your fact…"
            slow="Still saving your fact… This is taking longer than usual. You can leave this page."
            className="ml-feedback-phase" />
        )}
      </form>
      <p className="ml-note">Saved as typed. If it states a new value for something already known, the older fact is marked replaced.</p>
    </section>
  );
}

const TABS: { id: Tab; label: string }[] = [
  { id: 'facts', label: 'Facts' },
  { id: 'entities', label: 'Entities' },
  { id: 'sources', label: 'Excerpts' },
  { id: 'observations', label: 'Observations' },
];

/** True when the row passes the filter; an empty filter passes everything. */
function matches(text: string, filter: string): boolean {
  return !filter || text.toLowerCase().includes(filter.toLowerCase());
}

/**
 * Stored knowledge as four tabs over one filter.
 *
 * Every list stops at LIST_CAP rows until "Show all", which lasts as long as
 * the page is mounted. The observation tab also offers a reflect run, enabled
 * only while the extractor is a working endpoint.
 */
function Knowledge({ data, tab, onTab, filter, onFilter, onRemove, onKeep, onReflect, onEdit }: {
  data: LoopState;
  tab: Tab;
  onTab: (tab: Tab) => void;
  filter: string;
  onFilter: (value: string) => void;
  onRemove: (type: TargetType, id: number) => Promise<Ack>;
  onKeep: (id: number) => Promise<Ack>;
  onReflect: () => Promise<Outcome>;
  onEdit: (id: number, text: string) => Promise<Ack & { merged?: boolean }>;
}) {
  const [reflectActive, setReflectActive] = useState(false);
  const [reflectError, setReflectError] = useState<string | null>(null);
  const [reflectResult, setReflectResult] = useState<string | null>(null);
  const reflectPhase = useWaitPhase(reflectActive);
  /** Run one reflection on the AI; the result or its cause is said in place. */
  const askAi = async () => {
    if (reflectActive) return;
    setReflectActive(true);
    setReflectError(null);
    setReflectResult(null);
    const outcome = await onReflect();
    setReflectActive(false);
    if (!outcome.ok) {
      setReflectError(outcome.message);
      return;
    }
    const answer = outcome.data as { status?: string; cause?: string };
    setReflectResult(answer.status === 'degraded'
      ? (answer.cause || 'The AI could not run; the built-in rules took over.')
      : 'The AI proposed observations; they are waiting in the review queue.');
  };
  const sizes: Record<Tab, number> = {
    facts: data.facts.length,
    entities: data.entities.length,
    sources: data.sources.length,
    observations: data.observations.length,
  };
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  // Each list stops at LIST_CAP rows; "Show all" opens that tab's list
  // until the page reloads.
  const [opened, setOpened] = useState<Partial<Record<Tab, boolean>>>({});
  const cap = <T,>(rows: T[]): T[] => (opened[tab] ? rows : rows.slice(0, LIST_CAP));
  let matched = 0;
  const factsById = useMemo(() => new Map(data.facts.map((f) => [f.id, f])), [data.facts]);
  /** Walk the tabs with arrows, Home and End; every other key is left alone. */
  const onKeyDown = (event: ReactKeyboardEvent) => {
    const index = TABS.findIndex((t) => t.id === tab);
    const keys: Record<string, number> = {
      ArrowRight: (index + 1) % TABS.length,
      ArrowLeft: (index - 1 + TABS.length) % TABS.length,
      Home: 0,
      End: TABS.length - 1,
    };
    if (!(event.key in keys)) return;
    event.preventDefault();
    const next = TABS[keys[event.key]].id;
    onTab(next);
    tabRefs.current[next]?.focus();
  };
  let body: ReactNode;
  if (tab === 'facts') {
    const rows = data.facts.filter((f) => matches(`${f.text} ${f.entities.map((e) => e.name).join(' ')} ${f.origin.label}`, filter));
    matched = rows.length;
    body = rows.length === 0 ? <Empty filter={filter} noun="facts" /> : (
      <ul className="ml-rows">
        {cap(rows).map((fact) => (
          <FactItem key={fact.id} fact={fact} factsById={factsById} onRemove={onRemove}
            onKeep={onKeep} onEntity={(name) => onFilter(name)} onEdit={onEdit} />
        ))}
      </ul>
    );
  } else if (tab === 'entities') {
    const rows = data.entities.filter((e) => matches(`${e.name} ${e.aliases.join(' ')} ${e.type}`, filter));
    matched = rows.length;
    body = rows.length === 0 ? <Empty filter={filter} noun="entities" /> : (
      <ul className="ml-rows">{cap(rows).map((entity) => <EntityItem key={entity.id} entity={entity} onRemove={onRemove} />)}</ul>
    );
  } else if (tab === 'sources') {
    const rows = data.sources.filter((s) => matches(`${s.text} ${s.channelLabel}`, filter));
    matched = rows.length;
    body = rows.length === 0 ? <Empty filter={filter} noun="excerpts" /> : (
      <ul className="ml-rows">{cap(rows).map((source) => <SourceItem key={source.id} source={source} onRemove={onRemove} />)}</ul>
    );
  } else {
    const rows = data.observations.filter((o) => matches(`${o.entityName ?? ''} ${o.text}`, filter));
    matched = rows.length;
    body = (
      <>
        <div className="ml-subbar">
          <p className="ml-note">
            Each entity with two or more facts gets one short observation, rewritten whenever those facts change. Reflected ones come from the AI and stay until you remove them.
          </p>
          <WaitButton className="ml-btn" active={reflectActive} disabled={data.extractor.mode !== 'model'}
            idle="Ask your AI for observations" working="Asking your AI..."
            title={data.extractor.mode !== 'model' ? 'Needs a working AI connection' : undefined}
            onClick={() => void askAi()} />
        </div>
        {reflectError && (
          <p className="ml-feedback-error" role="alert">
            {reflectError}
            <button type="button" className="ml-text-btn" onClick={() => void askAi()}>Try again</button>
          </p>
        )}
        {reflectResult && <p className="ml-feedback-result" role="status">{reflectResult}</p>}
        {reflectPhase !== 'idle' && (
          <ul className="ml-rows">
            <li className="ml-row ml-feedback-placeholder">
              <div className="ml-row-main">
                <SkeletonLine className="mem-skeleton-short" />
                <SkeletonLine className="mem-skeleton-block" />
                <p className="ml-feedback-phase" role="status">
                  {reflectPhase === 'slow'
                    ? 'Still asking your AI… This is taking longer than usual. You can leave this page.'
                    : 'Asking your AI for observations…'}
                </p>
              </div>
            </li>
          </ul>
        )}
        {rows.length === 0 ? <Empty filter={filter} noun="observations" /> : (
          <ul className="ml-rows">
            {cap(rows).map((obs) => <ObservationItem key={obs.id} obs={obs} factsById={factsById} onRemove={onRemove} />)}
          </ul>
        )}
      </>
    );
  }
  return (
    <section className="ml-tile ml-span-12" id="ml-knowledge" aria-labelledby="ml-knowledge-h">
      <div className="ml-tile-head">
        <h2 className="ml-tag" id="ml-knowledge-h">Stored knowledge</h2>
        <div className="ml-filter">
          <label className="ml-sr" htmlFor="ml-filter">Filter</label>
          <input id="ml-filter" name="filter" type="search" autoComplete="off" placeholder="Filter by text or name…" value={filter} onChange={(e) => onFilter(e.target.value)} />
        </div>
      </div>
      <div className="ml-tabs" role="tablist" aria-label="Stored knowledge" onKeyDown={onKeyDown}>
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" id={`ml-tab-${t.id}`} aria-selected={tab === t.id}
            aria-controls="ml-tabpanel" tabIndex={tab === t.id ? 0 : -1}
            ref={(el) => { tabRefs.current[t.id] = el; }} onClick={() => onTab(t.id)}>
            {t.label} <span className="ml-mono">{sizes[t.id]}</span>
          </button>
        ))}
      </div>
      <div role="tabpanel" id="ml-tabpanel" aria-labelledby={`ml-tab-${tab}`}>
        {body}
        {matched > LIST_CAP && (
          <div className="ml-more">
            <span className="ml-quiet ml-mono">{opened[tab] ? matched : LIST_CAP} of {matched}</span>
            <button type="button" className="ml-text-btn" aria-expanded={Boolean(opened[tab])}
              onClick={() => setOpened((o) => ({ ...o, [tab]: !o[tab] }))}>
              {opened[tab] ? 'Show fewer' : `Show all ${matched}`}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

/** The single line a filtered or empty list shows in place of rows. */
function Empty({ filter, noun }: { filter: string; noun: string }) {
  return <p className="ml-quiet ml-pad">{filter ? `No ${noun} match “${filter}”.` : `No ${noun} yet.`}</p>;
}

/** A row's actions: its removal, and for a fact the edit beside it. */
function RowActions({ onRemove, removeText, onEdit }: {
  onRemove: () => Promise<Ack>; removeText: string; onEdit?: () => void;
}) {
  const [active, setActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Check what a removal touches, with the row saying why it could not. */
  const forget = async () => {
    if (active) return;
    setActive(true);
    setError(null);
    const outcome = await onRemove();
    setActive(false);
    if (!outcome.ok) setError(outcome.message ?? 'That could not be checked.');
  };
  return (
    <div className="ml-row-actions">
      <div className="ml-row-buttons">
        {onEdit && <button type="button" className="ml-btn" onClick={onEdit}>Edit</button>}
        <WaitButton className="ml-btn ml-btn-remove" active={active} idle={removeText}
          working="Checking..." onClick={() => void forget()} />
      </div>
      {error && (
        <p className="ml-feedback-error" role="alert">
          {error}
          <button type="button" className="ml-text-btn" onClick={() => void forget()}>Try again</button>
        </p>
      )}
    </div>
  );
}

/**
 * One fact row: its text, where it came from, and what replaced it.
 *
 * A replaced fact stays visible and marked, with "Keep both" to put it back in
 * recall, so nothing leaves the list without a trace. Edit rewrites the text
 * through the edit route; Forget is this fact's own removal.
 */
function FactItem({ fact, factsById, onRemove, onKeep, onEntity, onEdit }: {
  fact: FactRow;
  factsById: Map<number, FactRow>;
  onRemove: (type: TargetType, id: number) => Promise<Ack>;
  onKeep: (id: number) => Promise<Ack>;
  onEntity: (name: string) => void;
  onEdit: (id: number, text: string) => Promise<Ack & { merged?: boolean }>;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(fact.text);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [keeping, setKeeping] = useState(false);
  const [keepError, setKeepError] = useState<string | null>(null);
  const [keepResult, setKeepResult] = useState<string | null>(null);
  const newer = fact.replacedBy !== null ? factsById.get(fact.replacedBy) : undefined;
  /** Save the edited text; a failure keeps the box and says why under it. */
  const save = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    setResult(null);
    const saved = await onEdit(fact.id, text.trim());
    setSaving(false);
    if (!saved.ok) {
      setError(saved.message ?? 'The edit was not saved.');
      return;
    }
    setEditing(false);
    setResult(saved.merged ? 'Saved and merged with a matching fact.' : 'Saved. The stored fact now reads this way.');
  };
  /** Put the edit away and forget what was typed. */
  const cancel = () => { setEditing(false); setText(fact.text); };
  /** Put a replaced fact back in recall without leaving the list. */
  const keep = async () => {
    if (keeping) return;
    setKeeping(true);
    setKeepError(null);
    setKeepResult(null);
    const outcome = await onKeep(fact.id);
    setKeeping(false);
    if (!outcome.ok) setKeepError(outcome.message ?? 'That fact could not be kept.');
    else setKeepResult('Both facts are kept.');
  };
  return (
    <li className={`ml-row${fact.replacedBy !== null ? ' is-replaced' : ''}`} id={`ml-fact-${fact.id}`}>
      <div className="ml-row-main">
        {editing ? (
          <div className="ml-edit">
            <label className="ml-sr" htmlFor={`ml-fact-${fact.id}-edit`}>Edit fact</label>
            <textarea id={`ml-fact-${fact.id}-edit`} rows={2} value={text} autoComplete="off" onChange={(e) => setText(e.target.value)} />
          </div>
        ) : (
          <p className="ml-row-text">{fact.text}</p>
        )}
        {error && (
          <p className="ml-feedback-error" role="alert">
            {error}
            <button type="button" className="ml-text-btn" onClick={() => void save()}>Try again</button>
          </p>
        )}
        {result && <p className="ml-feedback-result" role="status">{result}</p>}
        <p className="ml-row-meta">
          <span>{fact.origin.label}</span>
          {fact.origin.how && <span>{fact.origin.how}</span>}
          <span>saved <span className="ml-mono">{stamp(fact.createdTs)}</span></span>
          {fact.occurredTs !== null && <span>happened <span className="ml-mono">{stamp(fact.occurredTs)}</span></span>}
        </p>
        {fact.entities.length > 0 && (
          <p className="ml-chips" aria-label="Mentions">
            {fact.entities.map((e) => (
              <button key={e.id} type="button" className="ml-entity" onClick={() => onEntity(e.name)}
                aria-label={`Filter by ${e.name}`}>{e.name}</button>
            ))}
          </p>
        )}
        {fact.replacedBy !== null && (
          <p className="ml-flag">
            Recall skips this one: {newer ? <>“{newer.text}” replaced it</> : 'a newer value replaced it'}.
            <WaitButton className="ml-text-btn" active={keeping} idle="Keep both" working="Keeping both..."
              onClick={() => void keep()} />
          </p>
        )}
        {keepResult && <p className="ml-feedback-result" role="status">{keepResult}</p>}
        {keepError && (
          <p className="ml-feedback-error" role="alert">
            {keepError}
            <button type="button" className="ml-text-btn" onClick={() => void keep()}>Try again</button>
          </p>
        )}
        {fact.replaces.length > 0 && (
          <p className="ml-note">Replaces {count(fact.replaces.length, 'older fact')}, which recall now skips.</p>
        )}
      </div>
      {editing ? (
        <div className="ml-row-actions">
          <div className="ml-row-buttons">
            <button type="button" className="ml-btn" disabled={saving} onClick={cancel}>Cancel</button>
            <WaitButton className="ml-btn ml-btn-primary" active={saving} disabled={!text.trim()}
              idle="Save" working="Saving..." onClick={() => void save()} />
          </div>
          {saving && (
            <WaitLine active working="Saving your edit…"
              slow="Still saving your edit… This is taking longer than usual. You can leave this page."
              className="ml-feedback-phase" />
          )}
        </div>
      ) : (
        <RowActions onRemove={() => onRemove('fact', fact.id)}
          removeText="Forget…" onEdit={() => setEditing(true)} />
      )}
    </li>
  );
}

/** One entity row: its name, type, aliases and how many facts mention it. */
function EntityItem({ entity, onRemove }: {
  entity: EntityRow; onRemove: (type: TargetType, id: number) => Promise<Ack>;
}) {
  return (
    <li className="ml-row">
      <div className="ml-row-main">
        <p className="ml-row-text">{entity.name}</p>
        <p className="ml-row-meta">
          <span>{entity.type}</span>
          <span>{count(entity.factCount, 'fact')}</span>
          {entity.aliases.length > 0 && <span>also {entity.aliases.join(', ')}</span>}
        </p>
      </div>
      <RowActions onRemove={() => onRemove('entity', entity.id)} removeText="Forget…" />
    </li>
  );
}

/** One retained excerpt, quoted, with how many facts were taken from it. */
function SourceItem({ source, onRemove }: {
  source: SourceRow; onRemove: (type: TargetType, id: number) => Promise<Ack>;
}) {
  return (
    <li className="ml-row">
      <div className="ml-row-main">
        <blockquote className="ml-quote">{source.text}</blockquote>
        <p className="ml-row-meta">
          <span>{source.channelLabel}</span>
          <span className="ml-mono">{stamp(source.createdTs)}</span>
          <span>{count(source.factIds.length, 'fact')} taken from it</span>
        </p>
      </div>
      <RowActions onRemove={() => onRemove('source', source.id)} removeText="Remove…" />
    </li>
  );
}

/**
 * One observation row: its writer, the facts it cites and its confidence.
 *
 * An observation that lost a cited fact is flagged with the moment it happened
 * and asks to be checked rather than being hidden.
 */
function ObservationItem({ obs, factsById, onRemove }: {
  obs: ObservationRow; factsById: Map<number, FactRow>; onRemove: (type: TargetType, id: number) => Promise<Ack>;
}) {
  return (
    <li className={`ml-row${obs.staleTs ? ' is-flagged' : ''}`}>
      <div className="ml-row-main">
        {obs.entityName && <p className="ml-row-eyebrow">{obs.entityName}</p>}
        <p className="ml-row-text">{obs.text}</p>
        <p className="ml-row-meta">
          <span>{observationWriter(obs)}</span>
          <span>cites {count(obs.factIds.filter((id) => factsById.has(id)).length, 'fact')}</span>
          <span className="ml-mono">{obs.confidence.toFixed(2)} confidence</span>
          <span className="ml-mono">{stamp(obs.updatedTs)}</span>
        </p>
        {obs.staleTs && (
          <p className="ml-flag">A fact it cited was removed at {stamp(obs.staleTs)}. Check it still holds, or remove it.</p>
        )}
      </div>
      <RowActions onRemove={() => onRemove('observation', obs.id)} removeText="Remove…" />
    </li>
  );
}

/**
 * One group of a removal plan, showing its first five lines.
 *
 * An empty group renders nothing; a longer one ends with "and N more", so a
 * plan stays readable however much the removal touches.
 */
function PlanList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  const shown = items.slice(0, 5);
  return (
    <div className="ml-plan-group">
      <h3>{title}</h3>
      <ul>
        {shown.map((item, index) => <li key={index}>{item}</li>)}
        {items.length > shown.length && <li className="ml-quiet">and {items.length - shown.length} more</li>}
      </ul>
    </div>
  );
}

// Each rewritten observation as it reads now (struck through) and as it
// will read after the removal, so nothing changes unseen.
/**
 * The observations a removal rewrites, as they read now and after, up to three.
 *
 * A null after means the summary is rebuilt from the facts that remain rather
 * than written at removal time.
 */
function RewriteList({ rows }: { rows: RemovalPlan['observationsUpdated'] }) {
  if (rows.length === 0) return null;
  const shown = rows.slice(0, 3);
  return (
    <div className="ml-plan-group">
      <h3>{rows.length === 1 ? 'Observation rewritten' : 'Observations rewritten'}</h3>
      <ul className="ml-rewrites">
        {shown.map((row) => (
          <li key={row.id}>
            <p className="ml-rewrite-old"><span className="ml-sr">Now: </span><s>{row.text}</s></p>
            {row.after !== null ? (
              <p className="ml-rewrite-new">
                <span className="ml-sr">After: </span>{row.after}
                <span className="ml-chip-quiet">{row.afterMethod === 'model' ? 'AI' : 'Built-in'}</span>
              </p>
            ) : <p className="ml-rewrite-new ml-quiet">Rewritten from the facts that remain.</p>}
          </li>
        ))}
        {rows.length > shown.length && <li className="ml-quiet">and {rows.length - shown.length} more</li>}
      </ul>
    </div>
  );
}

/**
 * The placeholder for a removal check that is taking over a second: the
 * dialog's own shape, one phase line, no blocked page beyond the scrim.
 */
function RemovePreviewSkeleton() {
  const phase = useWaitPhase(true);
  if (phase === 'idle') return null;
  return (
    <div className="ml-scrim">
      <div className="ml-dialog" role="dialog" aria-modal="true" aria-busy="true" aria-label="Checking the removal">
        <p className="ml-tag">Checking the removal</p>
        <h2 className="ml-dialog-title">Checking what else changes…</h2>
        <div className="ml-plan-group" aria-hidden="true">
          <SkeletonLine className="mem-skeleton-short" />
          <SkeletonLine />
          <SkeletonLine />
        </div>
        <WaitLine active working="Checking what else changes…"
          slow="Still checking… This is taking longer than usual. You can leave this page."
          className="ml-feedback-phase" />
      </div>
    </div>
  );
}

/**
 * The confirmation a removal opens: what goes, and what else changes.
 *
 * Escape and a click on the scrim cancel while the plan is shown; Tab stays
 * inside the dialog, and focus returns to whatever held it when it opened.
 * A failed removal keeps the dialog and the plan on screen with the reason.
 */
function RemoveDialog({ plan, onCancel, onConfirm }: { plan: RemovalPlan; onCancel: () => void; onConfirm: () => Promise<Ack> }) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const [working, setWorking] = useState(false);
  const workingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  workingRef.current = working;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    /** Close on Escape, and keep Tab inside the dialog's buttons. */
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !workingRef.current) onCancel();
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const stops = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not(:disabled)'));
      if (stops.length === 0) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previous?.focus?.();
    };
  }, [onCancel]);
  const noun = TARGET_NOUN[plan.target.type];
  const nothingElse = !plan.observationsRemoved.length && !plan.observationsUpdated.length && !plan.observationsFlagged.length
    && !plan.entitiesRemoved.length && !plan.factsRestored.length && !plan.sourcesRemoved.length;
  /** Run the removal; a refusal stays here with the plan intact. */
  const confirm = async () => {
    if (working) return;
    setWorking(true);
    setError(null);
    const outcome = await onConfirm();
    setWorking(false);
    if (!outcome.ok) setError(outcome.message ?? 'Nothing was removed.');
  };
  return (
    <div className="ml-scrim" onMouseDown={(e) => { if (!working && e.target === e.currentTarget) onCancel(); }}>
      <div className="ml-dialog" role="dialog" aria-modal="true" aria-labelledby="ml-dialog-h" ref={dialogRef}>
        <p className="ml-tag">Remove {noun}</p>
        <h2 id="ml-dialog-h" className="ml-dialog-title">{plan.target.label}</h2>
        {/* A fact is its own title; an entity or excerpt lists what goes with it. */}
        <PlanList title={plan.target.type === 'entity' ? 'Facts that mention it' : 'Facts taken from it'}
          items={plan.target.type === 'entity' || plan.target.type === 'source' ? plan.facts.map((f) => f.text) : []} />
        <RewriteList rows={plan.observationsUpdated} />
        <PlanList title="Observations removed" items={plan.observationsRemoved.map((o) => o.text)} />
        <PlanList title="Observations flagged for a look" items={plan.observationsFlagged.map((o) => o.text)} />
        <PlanList title="Entities forgotten, nothing else mentions them" items={plan.entitiesRemoved.map((e) => e.name)} />
        <PlanList title="Older facts back in recall" items={plan.factsRestored.map((f) => f.text)} />
        {plan.sourcesRemoved.length > 0 && (
          <p className="ml-note">{count(plan.sourcesRemoved.length, 'excerpt')} of the original conversation will be deleted too.</p>
        )}
        {nothingElse && plan.target.type !== 'observation' && <p className="ml-note">Nothing else changes.</p>}
        {working && (
          <WaitLine active working={`Removing ${noun}…`}
            slow="Still removing… This is taking longer than usual. You can leave this page."
            className="ml-feedback-phase" />
        )}
        {error && (
          <p className="ml-feedback-error" role="alert">
            {error}
            <button type="button" className="ml-text-btn" onClick={() => void confirm()}>Try again</button>
          </p>
        )}
        <div className="ml-actions ml-dialog-actions">
          <button type="button" className="ml-btn" ref={cancelRef} disabled={working} onClick={onCancel}>Cancel</button>
          <WaitButton className="ml-btn ml-btn-danger" active={working} idle={removeLabel(plan)}
            working="Removing..." onClick={() => void confirm()} />
        </div>
      </div>
    </div>
  );
}

/**
 * The undo bar: what went, the window, and a countdown that expires it.
 *
 * The countdown reads the expiry against the wall clock once a second and calls
 * onExpire at zero, so the bar goes away even if the tab slept. A pending undo
 * holds the bar open; a refusal stays in the bar with the next step.
 */
function UndoBar({ undo, onUndo, onExpire }: { undo: Undo; onUndo: () => Promise<Ack>; onExpire: () => void }) {
  const [left, setLeft] = useState(() => Math.max(0, Math.round(undo.expiresTs - Date.now() / 1000)));
  const [active, setActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRef = useRef(false);
  activeRef.current = active;
  useEffect(() => {
    const timer = window.setInterval(() => {
      const remaining = Math.max(0, Math.round(undo.expiresTs - Date.now() / 1000));
      setLeft(remaining);
      if (remaining <= 0 && !activeRef.current) onExpire();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [undo, onExpire]);
  /** Undo the removal; a failure keeps the bar for another try. */
  const run = async () => {
    if (active) return;
    setActive(true);
    setError(null);
    const outcome = await onUndo();
    setActive(false);
    if (!outcome.ok) setError(outcome.message ?? 'The removal could not be undone.');
  };
  return (
    <div className="ml-undo">
      <span role="status">{undo.summary}. You have {undo.windowS} seconds to undo.</span>
      <WaitButton className="ml-btn ml-btn-primary" active={active} idle="Undo" working="Undoing..."
        onClick={() => void run()} />
      <span className="ml-mono ml-undo-left" aria-hidden="true">{left}s</span>
      {active && (
        <WaitLine active working="Undoing the removal…"
          slow="Still undoing… This is taking longer than usual. You can leave this page."
          className="ml-feedback-phase" />
      )}
      {error && (
        <p className="ml-feedback-error" role="alert">
          {error}
          <button type="button" className="ml-text-btn" onClick={() => void run()}>Try again</button>
        </p>
      )}
    </div>
  );
}
