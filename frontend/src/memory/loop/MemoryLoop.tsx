// The Memory page: the loop a knowledge point goes through, laid out as
// the user works it. Capture proposes facts from the Assistant and
// Research; the review queue decides what is saved; the stored
// knowledge shows each fact with where it came from and what it
// changed; the graph traces provenance; removal says what else changes
// before anything is written, and can be undone for a short window.
//
// Reads GET /api/memory/loop and writes only through the server's own
// routes: /settings/toggle, /memory/add, the inbox card routes for
// review, /api/memory/remove(/preview), /api/memory/undo and
// /api/memory/facts/<id>/keep.
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react';
import { getJson, postJson } from '../../api';
import MemoryGraph from '../MemoryGraph';
import type { GraphNode } from '../types';
import { channelList, count, methodLabel, removeLabel, removedSummary, stamp, TARGET_NOUN } from './copy';
import type {
  Candidate, EntityRow, FactRow, LoopState, ObservationRow, RemovalDone, RemovalPlan, SourceRow, TargetType,
} from './types';

type Load =
  | { state: 'loading' }
  | { state: 'ready'; data: LoopState }
  | { state: 'failed'; message: string };

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
  // Tests pin the graph's width; the page measures its own box.
  graphWidth?: number;
}

async function errorOf(res: { status: number; data: unknown }, fallback: string): Promise<string> {
  if (res.status === 401) return 'Your session ended. Open Nexuus Bot from its shortcut to get a fresh link.';
  const error = (res.data as { error?: string; cause?: string }).error ?? (res.data as { cause?: string }).cause;
  return error ? `${fallback} ${error}` : fallback;
}

export default function MemoryLoop({ endpoint = '/api/memory/loop', pollMs = 8000, graphWidth }: MemoryLoopProps) {
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [graphKey, setGraphKey] = useState(0);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [plan, setPlan] = useState<RemovalPlan | null>(null);
  const [undo, setUndo] = useState<Undo | null>(null);
  const [removedCount, setRemovedCount] = useState(0);
  const [tab, setTab] = useState<Tab>('facts');
  const [filter, setFilter] = useState('');

  const refresh = useCallback(async (graph = false) => {
    try {
      const res = await getJson(endpoint);
      if (res.ok) setLoad({ state: 'ready', data: res.data as LoopState });
      else setLoad({ state: 'failed', message: await errorOf(res, 'Memory could not be read.') });
    } catch {
      setLoad({ state: 'failed', message: 'The page could not reach its own server.' });
    }
    if (graph) setGraphKey((key) => key + 1);
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

  const act = useCallback(async (url: string, body: unknown, failure: string): Promise<unknown | null> => {
    try {
      const res = await postJson(url, body);
      if (!res.ok) {
        setNotice(await errorOf(res, failure));
        return null;
      }
      return res.data;
    } catch {
      setNotice('The page could not reach its own server; nothing changed.');
      return null;
    }
  }, []);

  const askRemoval = useCallback(async (type: TargetType, id: number) => {
    const data = await act('/api/memory/remove/preview', { target: { type, id } }, 'That could not be checked.');
    if (data) setPlan((data as { plan: RemovalPlan }).plan);
  }, [act]);

  const confirmRemoval = useCallback(async () => {
    if (!plan) return;
    const data = await act('/api/memory/remove', { target: { type: plan.target.type, id: plan.target.id } }, 'Nothing was removed.');
    setPlan(null);
    if (!data) return;
    const answer = data as { removed: RemovalDone; undo: { token: string; expiresTs: number } };
    setUndo({
      token: answer.undo.token, expiresTs: answer.undo.expiresTs,
      windowS: load.state === 'ready' ? load.data.undoWindowS : 30, summary: removedSummary(answer.removed),
    });
    setRemovedCount((n) => n + (answer.removed.facts.length || 1));
    setFocusId(null);
    await refresh(true);
  }, [act, plan, refresh, load]);

  const runUndo = useCallback(async () => {
    if (!undo) return;
    const data = await act('/api/memory/undo', { token: undo.token }, 'The removal could not be undone.');
    setUndo(null);
    if (data) {
      setRemovedCount(0);
      setNotice('Removal undone. Everything it touched is back.');
    }
    await refresh(true);
  }, [act, undo, refresh]);

  const graphRemove = useCallback((node: GraphNode) => {
    const [kind, raw] = node.id.split(':');
    const id = Number(raw);
    if (!Number.isInteger(id)) return;
    if (kind === 'fact' || kind === 'entity' || kind === 'source' || kind === 'observation') void askRemoval(kind, id);
  }, [askRemoval]);

  const closePlan = useCallback(() => setPlan(null), []);
  const dropUndo = useCallback(() => setUndo(null), []);

  const showInGraph = useCallback((nodeId: string) => {
    setFocusId(nodeId);
    document.getElementById('ml-graph')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  if (load.state === 'loading') {
    return <div className="ml"><p className="ml-quiet" role="status">Reading memory…</p></div>;
  }
  if (load.state === 'failed') {
    return (
      <div className="ml">
        <header className="ml-head"><h1>Memory</h1></header>
        <p className="ml-alert" role="alert">{load.message}</p>
      </div>
    );
  }
  const data = load.data;

  return (
    <div className="ml">
      <Header data={data} />
      <Flow data={data} removedCount={removedCount} />
      {notice && (
        <p className="ml-notice" role="status">
          {notice}
          <button type="button" className="ml-text-btn" onClick={() => setNotice(null)}>Dismiss</button>
        </p>
      )}
      <div className="ml-grid">
        <Review data={data} act={act} onChanged={() => refresh(true)} />
        <div className="ml-side">
          <CaptureSettings data={data} act={act} onChanged={() => refresh()} />
          <AddFact act={act} onChanged={() => refresh(true)} />
        </div>
        <Knowledge
          data={data}
          tab={tab}
          onTab={setTab}
          filter={filter}
          onFilter={setFilter}
          onRemove={askRemoval}
          onShow={showInGraph}
          onKeep={async (id) => {
            if (await act(`/api/memory/facts/${id}/keep`, {}, 'That fact could not be kept.')) await refresh(true);
          }}
          onReflect={async () => {
            const res = await act('/memory/reflect', {}, 'Observations could not be derived.');
            if (res && (res as { status?: string }).status === 'degraded') setNotice((res as { cause: string }).cause);
            else if (res) setNotice('The endpoint proposed observations; they are waiting in the review queue.');
            await refresh();
          }}
        />
        <section className="ml-tile ml-span-12" id="ml-graph" aria-labelledby="ml-graph-h">
          <div className="ml-tile-head">
            <h2 className="ml-tag" id="ml-graph-h">Provenance graph</h2>
            <a className="ml-tile-link" href="/memory/graph">Open full page</a>
          </div>
          <p className="ml-tile-sub">Select any point to see where it came from and what it links to.</p>
          <div id="memory-graph-root">
            <MemoryGraph chrome={false} reloadKey={graphKey} focusId={focusId} onRemove={graphRemove} initialWidth={graphWidth} />
          </div>
        </section>
      </div>
      {plan && <RemoveDialog plan={plan} onCancel={closePlan} onConfirm={confirmRemoval} />}
      {undo && <UndoBar undo={undo} onUndo={runUndo} onExpire={dropUndo} />}
    </div>
  );
}

type Act = (url: string, body: unknown, failure: string) => Promise<unknown | null>;

function Header({ data }: { data: LoopState }) {
  const on = data.capture.channels.filter((c) => c.on).map((c) => c.label);
  const capture = !data.capture.enabled || on.length === 0
    ? 'Capture is off: facts arrive only when you type or approve them.'
    : `Capturing from ${channelList(on)}. ${data.capture.autoApprove ? 'New facts are saved automatically.' : 'New facts wait for your review.'}`;
  return (
    <header className="ml-head">
      <div>
        <h1>Memory</h1>
        <p className="ml-sub">
          {count(data.counts.standing, 'fact')} the assistant can recall, across {count(data.counts.entities, 'entity', 'entities')}. {capture}
        </p>
      </div>
    </header>
  );
}

function Flow({ data, removedCount }: { data: LoopState; removedCount: number }) {
  const last = data.lastCapture;
  const lastLine = last
    ? `Last from ${last.channelLabel} at ${stamp(last.ts)}: ${count(last.found, 'fact')} found, ${last.staged} to review, ${last.stored} saved.`
    : 'Nothing captured since the app started.';
  const steps: { id: string; tag: string; figure: number; unit: string; line: string; href: string; mark?: string }[] = [
    {
      id: 'capture', tag: 'Capture', figure: data.counts.waiting, unit: 'waiting for review',
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
            <span className="ml-step-unit">{step.unit}</span>
            <span className="ml-step-line">{step.line}</span>
          </a>
        </li>
      ))}
    </ol>
  );
}

function Review({ data, act, onChanged }: { data: LoopState; act: Act; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const decide = async (candidate: Candidate, decision: 'accept' | 'dismiss', text?: string) => {
    setBusy(candidate.cardId);
    if (decision === 'accept' && text !== undefined && text.trim() && text.trim() !== candidate.text) {
      const edited = await act(`/inbox/cards/${candidate.cardId}/edit`, { draft: text.trim() }, 'The edit was not saved.');
      if (!edited) { setBusy(null); return; }
    }
    await act(`/inbox/cards/${candidate.cardId}/${decision}`, {}, decision === 'accept' ? 'It was not saved.' : 'It was not rejected.');
    setBusy(null);
    onChanged();
  };
  const approveAll = async () => {
    setBusy('all');
    for (const candidate of data.candidates) {
      await act(`/inbox/cards/${candidate.cardId}/accept`, {}, 'One candidate was not saved.');
    }
    setBusy(null);
    onChanged();
  };
  return (
    <section className="ml-tile ml-span-8 ml-review" id="ml-review" aria-labelledby="ml-review-h">
      <div className="ml-tile-head">
        <h2 className="ml-tag" id="ml-review-h">Review</h2>
        <span className="ml-tile-count">{count(data.candidates.length, 'candidate')}</span>
        {data.candidates.length > 1 && (
          <button type="button" className="ml-btn" disabled={busy !== null} onClick={approveAll}>Approve all</button>
        )}
      </div>
      {data.candidates.length === 0 ? (
        <div className="ml-empty">
          <p className="ml-empty-title">Nothing to review</p>
          <p>
            {data.capture.enabled && !data.capture.autoApprove
              ? 'When you tell the Assistant or Research something worth keeping, the facts it finds wait here before they are saved.'
              : data.capture.autoApprove
                ? 'Auto-approve is on, so captured facts are saved straight to memory. Turn on review in Capture settings to check them first.'
                : 'Capture is off. Turn it on in Capture settings, or type a fact yourself.'}
          </p>
        </div>
      ) : (
        <ul className="ml-cands">
          {data.candidates.map((candidate) => (
            <CandidateItem key={candidate.cardId} candidate={candidate} busy={busy !== null} onDecide={decide} />
          ))}
        </ul>
      )}
    </section>
  );
}

function CandidateItem({ candidate, busy, onDecide }: {
  candidate: Candidate;
  busy: boolean;
  onDecide: (candidate: Candidate, decision: 'accept' | 'dismiss', text?: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(candidate.text);
  const id = `ml-cand-${candidate.cardId}`;
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
          <summary>From what was said</summary>
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
        <button type="button" className="ml-btn ml-btn-primary" disabled={busy}
          onClick={() => onDecide(candidate, 'accept', editing ? text : undefined)}>
          {editing ? 'Save edited' : 'Approve'}
        </button>
        {!editing && candidate.type === 'fact' && (
          <button type="button" className="ml-btn" disabled={busy} onClick={() => setEditing(true)}>Edit</button>
        )}
        {editing && (
          <button type="button" className="ml-btn" onClick={() => { setEditing(false); setText(candidate.text); }}>Cancel edit</button>
        )}
        <button type="button" className="ml-btn" disabled={busy} onClick={() => onDecide(candidate, 'dismiss')}>Reject</button>
      </div>
    </li>
  );
}

function Switch({ id, label, hint, on, disabled, onToggle }: {
  id: string; label: string; hint?: string; on: boolean; disabled?: boolean; onToggle: () => void;
}) {
  return (
    <div className={`ml-switch-row${disabled ? ' is-disabled' : ''}`}>
      <span className="ml-switch-label" id={`${id}-label`}>
        {label}
        {hint && <span className="ml-switch-hint">{hint}</span>}
      </span>
      <button type="button" role="switch" aria-checked={on} aria-labelledby={`${id}-label`}
        className="ml-switch" disabled={disabled} onClick={onToggle}>
        <span className="ml-switch-knob" />
      </button>
    </div>
  );
}

function CaptureSettings({ data, act, onChanged }: { data: LoopState; act: Act; onChanged: () => void }) {
  const toggle = async (key: string) => {
    if (await act('/settings/toggle', { key }, 'The setting was not changed.')) onChanged();
  };
  const capture = data.capture;
  return (
    <section className="ml-tile" aria-labelledby="ml-capture-h">
      <div className="ml-tile-head">
        <h2 className="ml-tag" id="ml-capture-h">Capture settings</h2>
      </div>
      <Switch id="ml-sw-capture" label="Capture facts as you work" on={capture.enabled}
        onToggle={() => toggle('memory_capture')} />
      <fieldset className="ml-fieldset" disabled={!capture.enabled}>
        <legend>Read from</legend>
        {capture.channels.map((channel) => (
          <Switch key={channel.id} id={`ml-sw-${channel.id}`} label={channel.label}
            hint={channel.id === 'assistant' ? 'Your questions and its answers' : 'Your questions and the sourced summary'}
            on={channel.on} disabled={!capture.enabled} onToggle={() => toggle(channel.setting)} />
        ))}
      </fieldset>
      <fieldset className="ml-fieldset" disabled={!capture.enabled}>
        <legend>When a fact is found</legend>
        <div className="ml-segment" role="radiogroup" aria-label="When a fact is found">
          <button type="button" role="radio" aria-checked={!capture.autoApprove}
            onClick={() => capture.autoApprove && toggle('memory_auto_approve')}>Ask me first</button>
          <button type="button" role="radio" aria-checked={capture.autoApprove}
            onClick={() => !capture.autoApprove && toggle('memory_auto_approve')}>Save automatically</button>
        </div>
      </fieldset>
      <p className="ml-note">{data.extractor.detail}</p>
      {data.lastCapture?.cause && (
        <p className="ml-note">Last endpoint error: {data.lastCapture.cause}</p>
      )}
    </section>
  );
}

function AddFact({ act, onChanged }: { act: Act; onChanged: () => void }) {
  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);
  const [empty, setEmpty] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!text.trim()) {
      setEmpty(true);
      inputRef.current?.focus();
      return;
    }
    setSaving(true);
    const ok = await act('/memory/add', { text: text.trim() }, 'The fact was not saved.');
    setSaving(false);
    if (ok) {
      setText('');
      onChanged();
    }
  };
  return (
    <section className="ml-tile" aria-labelledby="ml-add-h">
      <div className="ml-tile-head"><h2 className="ml-tag" id="ml-add-h">Add a fact</h2></div>
      <form className="ml-add" onSubmit={submit}>
        <label className="ml-sr" htmlFor="ml-add-input">Fact</label>
        <textarea id="ml-add-input" name="fact" ref={inputRef} rows={2} value={text} autoComplete="off"
          placeholder="The Acme renewal is due December 15…" aria-invalid={empty || undefined}
          aria-describedby={empty ? 'ml-add-error' : undefined}
          onChange={(e) => { setText(e.target.value); setEmpty(false); }} />
        {empty && <p className="ml-field-error" id="ml-add-error">Type the fact first, in one sentence.</p>}
        <button type="submit" className="ml-btn ml-btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save fact'}</button>
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

function matches(text: string, filter: string): boolean {
  return !filter || text.toLowerCase().includes(filter.toLowerCase());
}

function Knowledge({ data, tab, onTab, filter, onFilter, onRemove, onShow, onKeep, onReflect }: {
  data: LoopState;
  tab: Tab;
  onTab: (tab: Tab) => void;
  filter: string;
  onFilter: (value: string) => void;
  onRemove: (type: TargetType, id: number) => void;
  onShow: (nodeId: string) => void;
  onKeep: (id: number) => void;
  onReflect: () => void;
}) {
  const sizes: Record<Tab, number> = {
    facts: data.facts.length,
    entities: data.entities.length,
    sources: data.sources.length,
    observations: data.observations.length,
  };
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const factsById = useMemo(() => new Map(data.facts.map((f) => [f.id, f])), [data.facts]);
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
    body = rows.length === 0 ? <Empty filter={filter} noun="facts" /> : (
      <ul className="ml-rows">
        {rows.map((fact) => (
          <FactItem key={fact.id} fact={fact} factsById={factsById} onRemove={onRemove} onShow={onShow}
            onKeep={onKeep} onEntity={(name) => onFilter(name)} />
        ))}
      </ul>
    );
  } else if (tab === 'entities') {
    const rows = data.entities.filter((e) => matches(`${e.name} ${e.aliases.join(' ')} ${e.type}`, filter));
    body = rows.length === 0 ? <Empty filter={filter} noun="entities" /> : (
      <ul className="ml-rows">{rows.map((entity) => <EntityItem key={entity.id} entity={entity} onRemove={onRemove} onShow={onShow} />)}</ul>
    );
  } else if (tab === 'sources') {
    const rows = data.sources.filter((s) => matches(`${s.text} ${s.channelLabel}`, filter));
    body = rows.length === 0 ? <Empty filter={filter} noun="excerpts" /> : (
      <ul className="ml-rows">{rows.map((source) => <SourceItem key={source.id} source={source} onRemove={onRemove} onShow={onShow} />)}</ul>
    );
  } else {
    const rows = data.observations.filter((o) => matches(o.text, filter));
    body = (
      <>
        <div className="ml-subbar">
          <p className="ml-note">
            Consolidated observations are rebuilt whenever their facts change. Reflected ones come from the endpoint and are kept until you remove them.
          </p>
          <button type="button" className="ml-btn" onClick={onReflect} disabled={data.extractor.mode !== 'model'}
            title={data.extractor.mode !== 'model' ? 'Needs a working endpoint' : undefined}>
            Ask the endpoint for observations
          </button>
        </div>
        {rows.length === 0 ? <Empty filter={filter} noun="observations" /> : (
          <ul className="ml-rows">
            {rows.map((obs) => <ObservationItem key={obs.id} obs={obs} factsById={factsById} onRemove={onRemove} onShow={onShow} />)}
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
      <div role="tabpanel" id="ml-tabpanel" aria-labelledby={`ml-tab-${tab}`}>{body}</div>
    </section>
  );
}

function Empty({ filter, noun }: { filter: string; noun: string }) {
  return <p className="ml-quiet ml-pad">{filter ? `No ${noun} match “${filter}”.` : `No ${noun} yet.`}</p>;
}

function RowActions({ onShow, onRemove, removeText }: { onShow?: () => void; onRemove: () => void; removeText: string }) {
  return (
    <div className="ml-row-actions">
      {onShow && <button type="button" className="ml-text-btn" onClick={onShow}>Show in graph</button>}
      <button type="button" className="ml-btn ml-btn-remove" onClick={onRemove}>{removeText}</button>
    </div>
  );
}

function FactItem({ fact, factsById, onRemove, onShow, onKeep, onEntity }: {
  fact: FactRow;
  factsById: Map<number, FactRow>;
  onRemove: (type: TargetType, id: number) => void;
  onShow: (nodeId: string) => void;
  onKeep: (id: number) => void;
  onEntity: (name: string) => void;
}) {
  const newer = fact.replacedBy !== null ? factsById.get(fact.replacedBy) : undefined;
  return (
    <li className={`ml-row${fact.replacedBy !== null ? ' is-replaced' : ''}`} id={`ml-fact-${fact.id}`}>
      <div className="ml-row-main">
        <p className="ml-row-text">{fact.text}</p>
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
            <button type="button" className="ml-text-btn" onClick={() => onKeep(fact.id)}>Keep both</button>
          </p>
        )}
        {fact.replaces.length > 0 && (
          <p className="ml-note">Replaces {count(fact.replaces.length, 'older fact')}, which recall now skips.</p>
        )}
      </div>
      <RowActions onShow={() => onShow(`fact:${fact.id}`)} onRemove={() => onRemove('fact', fact.id)} removeText="Remove…" />
    </li>
  );
}

function EntityItem({ entity, onRemove, onShow }: {
  entity: EntityRow; onRemove: (type: TargetType, id: number) => void; onShow: (nodeId: string) => void;
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
      <RowActions onShow={() => onShow(`entity:${entity.id}`)} onRemove={() => onRemove('entity', entity.id)} removeText="Forget…" />
    </li>
  );
}

function SourceItem({ source, onRemove, onShow }: {
  source: SourceRow; onRemove: (type: TargetType, id: number) => void; onShow: (nodeId: string) => void;
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
      <RowActions onShow={() => onShow(`source:${source.id}`)} onRemove={() => onRemove('source', source.id)} removeText="Remove…" />
    </li>
  );
}

function ObservationItem({ obs, factsById, onRemove, onShow }: {
  obs: ObservationRow; factsById: Map<number, FactRow>; onRemove: (type: TargetType, id: number) => void; onShow: (nodeId: string) => void;
}) {
  return (
    <li className={`ml-row${obs.staleTs ? ' is-flagged' : ''}`}>
      <div className="ml-row-main">
        <p className="ml-row-text">{obs.text}</p>
        <p className="ml-row-meta">
          <span>{obs.derived === 'consolidated' ? 'Consolidated' : 'Reflected'}</span>
          <span>cites {count(obs.factIds.filter((id) => factsById.has(id)).length, 'fact')}</span>
          <span className="ml-mono">{obs.confidence.toFixed(2)} confidence</span>
          <span className="ml-mono">{stamp(obs.updatedTs)}</span>
        </p>
        {obs.staleTs && (
          <p className="ml-flag">A fact it cited was removed at {stamp(obs.staleTs)}. Check it still holds, or remove it.</p>
        )}
      </div>
      <RowActions onShow={() => onShow(`observation:${obs.id}`)} onRemove={() => onRemove('observation', obs.id)} removeText="Remove…" />
    </li>
  );
}

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

function RemoveDialog({ plan, onCancel, onConfirm }: { plan: RemovalPlan; onCancel: () => void; onConfirm: () => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const [working, setWorking] = useState(false);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel();
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
  return (
    <div className="ml-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="ml-dialog" role="dialog" aria-modal="true" aria-labelledby="ml-dialog-h" ref={dialogRef}>
        <p className="ml-tag">Remove {noun}</p>
        <h2 id="ml-dialog-h" className="ml-dialog-title">{plan.target.label}</h2>
        {/* A fact is its own title; an entity or excerpt lists what goes with it. */}
        <PlanList title={plan.target.type === 'entity' ? 'Facts that mention it' : 'Facts taken from it'}
          items={plan.target.type === 'entity' || plan.target.type === 'source' ? plan.facts.map((f) => f.text) : []} />
        <PlanList title="Observations rewritten without it" items={plan.observationsUpdated.map((o) => o.text)} />
        <PlanList title="Observations removed" items={plan.observationsRemoved.map((o) => o.text)} />
        <PlanList title="Observations flagged for a look" items={plan.observationsFlagged.map((o) => o.text)} />
        <PlanList title="Entities forgotten, nothing else mentions them" items={plan.entitiesRemoved.map((e) => e.name)} />
        <PlanList title="Older facts back in recall" items={plan.factsRestored.map((f) => f.text)} />
        {plan.sourcesRemoved.length > 0 && (
          <p className="ml-note">{count(plan.sourcesRemoved.length, 'excerpt')} of the original conversation will be deleted too.</p>
        )}
        {nothingElse && plan.target.type !== 'observation' && <p className="ml-note">Nothing else changes.</p>}
        <div className="ml-actions ml-dialog-actions">
          <button type="button" className="ml-btn" ref={cancelRef} onClick={onCancel}>Cancel</button>
          <button type="button" className="ml-btn ml-btn-danger" disabled={working}
            onClick={() => { setWorking(true); onConfirm(); }}>{removeLabel(plan)}</button>
        </div>
      </div>
    </div>
  );
}

function UndoBar({ undo, onUndo, onExpire }: { undo: Undo; onUndo: () => void; onExpire: () => void }) {
  const [left, setLeft] = useState(() => Math.max(0, Math.round(undo.expiresTs - Date.now() / 1000)));
  useEffect(() => {
    const timer = window.setInterval(() => {
      const remaining = Math.max(0, Math.round(undo.expiresTs - Date.now() / 1000));
      setLeft(remaining);
      if (remaining <= 0) onExpire();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [undo, onExpire]);
  return (
    <div className="ml-undo">
      <span role="status">{undo.summary}. You have {undo.windowS} seconds to undo.</span>
      <button type="button" className="ml-btn ml-btn-primary" onClick={onUndo}>Undo</button>
      <span className="ml-mono ml-undo-left" aria-hidden="true">{left}s</span>
    </div>
  );
}
