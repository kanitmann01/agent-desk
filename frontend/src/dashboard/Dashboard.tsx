// The dashboard composition, driven entirely by the /api/dashboard
// payload: the rail, the hero band (the one display greeting, the date
// line, the one honest source line), the research command bar, and the
// bento grid (sales hero, commitment, research answer, skills, plugin
// cards) rendered in the layout's order, then the footer. The greeting
// and date line are computed client-side; the source line is only ever
// the truth, as on the server-rendered page.
//
// Customize mode (issue #66) rearranges that composition: every visible
// card is wrapped in its CustomizeCell (grab handle, Move up/down,
// Rename, Hide), hidden cards wait in the Hidden cards strip with
// Restore, and the pinned save model is save-on-every-action: each
// reorder, rename, hide or restore POSTs the full desired layout to
// /api/layout immediately and refetches the payload, so there is no
// separate Save step and nothing to lose by leaving customize.
import { useEffect, useRef, useState } from 'react';
import { getJson, postJson } from '../api';
import { dateLineFor, greetingFor } from '../fmt';
import type { DashboardData, LayoutCardState } from '../types';
import Rail from './Rail';
import SalesCard from './SalesCard';
import CommitmentsCard from './CommitmentsCard';
import ResearchCard, { RESEARCH_BUSY, UNREACHABLE_SEND, type ResearchAnswer } from './ResearchCard';
import PluginCardView from './PluginCardView';
import SkillsCard from './SkillsCard';
import CustomizeCell from './CustomizeCell';
import Brief from './Brief';
import CommandBar from '../components/CommandBar';
import Button from '../components/Button';

interface DashboardProps {
  data: DashboardData;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

interface SkillResponse {
  status?: string;
  summary?: string;
  reply?: string;
  cause?: string;
}

interface ResearchResponse {
  status?: string;
  cause?: string;
  summary?: string;
  sources?: string[];
}

// The default display names of the builtin cards; a plugin card's name
// is its payload title (already carrying any layout override).
const DEFAULT_CARD_TITLES: Record<string, string> = {
  sales: 'Sales, last 24 hours',
  commitments: "Today's key commitment",
  research: 'Research',
  skills: 'Your skills',
};

const SAVE_UNREACHABLE = 'The dashboard could not reach its own server; the layout was not saved.';
const SAVE_REFUSED = 'The layout was not saved; the dashboard re-read the saved layout.';

export default function Dashboard({ data, onRefetch, onExpired }: DashboardProps) {
  // The skills strip and the research bar share one answer area and one
  // status line, exactly as the server-rendered page does.
  const [answer, setAnswer] = useState<ResearchAnswer | null>(null);
  const [answerSeq, setAnswerSeq] = useState(0);
  const [statusText, setStatusText] = useState('');
  const [skillBusyId, setSkillBusyId] = useState<number | null>(null);
  const [researchBusy, setResearchBusy] = useState(false);

  // Customize mode: the full layout (hidden cards included) lives here,
  // read from /api/layout on entering and kept in step with every save.
  const [customizing, setCustomizing] = useState(false);
  const [layoutState, setLayoutState] = useState<LayoutCardState[] | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [customizeNote, setCustomizeNote] = useState('');
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [dragOverKey, setDragOverKey] = useState<string | null>(null);
  // Where focus should land after an action removes or moves the
  // focused control (the Restore button of a just-hidden card, the grab
  // handle of a restored or renamed card).
  const focusPending = useRef<{ kind: 'grip' | 'restore'; key: string } | null>(null);

  const now = new Date();
  const greeting = greetingFor(now);
  const dateLine = dateLineFor(now);
  const connected = data.sources.connected;
  const sourceLine = connected > 0
    ? `Live: ${connected} of ${data.sources.total} sources connected.`
    : '';

  // The layout the payload carries: visible cards only, in render
  // order, custom titles riding along.
  const visible = data.layout.cards;
  const hasSkills = data.skills.length > 0;
  // The skills card renders only when the layout shows it AND there are
  // skills to list; a card with nothing honest to say is not a card.
  const skillsShown = visible.some((c) => c.key === 'skills') && hasSkills;

  function layoutTitle(key: string): string | null {
    const fromState = layoutState?.find((c) => c.key === key);
    if (fromState) return fromState.title;
    return visible.find((c) => c.key === key)?.title ?? null;
  }

  function cardName(key: string): string {
    const plugin = data.plugins.cards.find((c) => c.id === key);
    return layoutTitle(key) ?? DEFAULT_CARD_TITLES[key] ?? plugin?.title ?? key;
  }

  // Does this layout key render a card at all right now? (The skills
  // card needs skills; a plugin key needs its installed card.)
  function rendersCard(key: string): boolean {
    if (key === 'skills') return hasSkills;
    if (!(key in DEFAULT_CARD_TITLES)) {
      return data.plugins.cards.some((c) => c.id === key);
    }
    return true;
  }

  function showAnswer(next: ResearchAnswer | null) {
    setAnswer(next);
    setAnswerSeq((seq) => seq + 1);
  }

  async function ask(question: string): Promise<boolean> {
    setResearchBusy(true);
    setStatusText(RESEARCH_BUSY);
    let res;
    try {
      res = await postJson('/research', { question });
    } catch {
      setResearchBusy(false);
      setStatusText(UNREACHABLE_SEND);
      return false;
    }
    setResearchBusy(false);
    if (res.status === 401) { onExpired(); return false; }
    const d = (res.data ?? {}) as ResearchResponse;
    if (d.status === 'degraded') {
      showAnswer(null);
      setStatusText(d.cause || 'The company endpoint did not answer.');
      return false;
    }
    setStatusText('');
    showAnswer({
      question,
      summary: d.summary || '',
      sources: d.sources || [],
    });
    void onRefetch(); // the stamp moves to Answered HH:MM
    return true;
  }

  async function runSkill(id: number) {
    setSkillBusyId(id);
    setStatusText('Running the saved ask');
    let res;
    try {
      res = await postJson(`/skills/${id}/run`);
    } catch {
      setSkillBusyId(null);
      setStatusText('The dashboard could not reach its own server; nothing was sent.');
      return;
    }
    setSkillBusyId(null);
    if (res.status === 401) { onExpired(); return; }
    setStatusText('');
    const d = (res.data ?? {}) as SkillResponse;
    showAnswer({
      question: d.status === 'ok' ? 'Skill result' : 'Skill unavailable',
      summary: d.status === 'ok' ? (d.summary || d.reply || '') : (d.cause || ''),
      sources: [],
    });
  }

  // -- customize mode ---------------------------------------------------

  // The layout read, guarded like every other call the cards make: a
  // rejected fetch answers null (the server is unreachable) instead of
  // escaping as an unhandled rejection.
  async function readLayout() {
    try {
      return await getJson('/api/layout');
    } catch {
      return null;
    }
  }

  async function enterCustomize() {
    const res = await readLayout();
    if (res !== null && res.status === 401) { onExpired(); return; }
    if (res === null) {
      setCustomizeNote('The dashboard could not reach its own server; customize did not open.');
      return;
    }
    if (!res.ok) {
      setCustomizeNote('The dashboard could not read the layout; customize did not open.');
      return;
    }
    const d = (res.data ?? {}) as { cards?: LayoutCardState[] };
    setLayoutState(Array.isArray(d.cards) ? d.cards : []);
    setCustomizeNote('');
    setRenaming(null);
    setCustomizing(true);
  }

  function leaveCustomize() {
    setCustomizing(false);
    setRenaming(null);
    setDragKey(null);
    setDragOverKey(null);
    setCustomizeNote('');
  }

  async function resyncLayout() {
    const res = await readLayout();
    if (res === null) return; // unreachable: the screen keeps what it has
    if (res.status === 401) { onExpired(); return; }
    const d = (res.data ?? {}) as { cards?: LayoutCardState[] };
    setLayoutState(Array.isArray(d.cards) ? d.cards : []);
    await onRefetch();
  }

  // The one save path: optimistic (the click is the truth), then the
  // POST, then the server's listing wins and the payload refetches so
  // the bento follows. A failure re-reads the server's copy, so the
  // screen never shows an arrangement that was not saved.
  async function saveLayout(next: LayoutCardState[], note: string) {
    setLayoutState(next);
    setCustomizeNote(note);
    let res;
    try {
      res = await postJson('/api/layout', { cards: next });
    } catch {
      res = null;
    }
    if (res !== null && res.status === 401) { onExpired(); return; }
    if (res === null || !res.ok) {
      setCustomizeNote(res === null ? SAVE_UNREACHABLE : SAVE_REFUSED);
      await resyncLayout();
      return;
    }
    const d = (res.data ?? {}) as { cards?: LayoutCardState[] };
    setLayoutState(Array.isArray(d.cards) ? d.cards : next);
    setCustomizeNote(note);
    await onRefetch();
  }

  // Reorder within the sequence of cards that actually render; hidden
  // and empty cards keep their slots around them.
  function moveRendered(key: string, toIndex: number) {
    if (layoutState === null) return;
    const cards = layoutState;
    const byKey = new Map(cards.map((c) => [c.key, c]));
    const movable = cards.filter((c) => !c.hidden && rendersCard(c.key)).map((c) => c.key);
    const from = movable.indexOf(key);
    if (from === -1) return;
    const target = Math.max(0, Math.min(movable.length - 1, toIndex));
    const reordered = [...movable];
    reordered.splice(target, 0, reordered.splice(from, 1)[0]);
    let next = 0;
    const rebuilt = cards.map((c) => {
      if (c.hidden || !rendersCard(c.key)) return { ...c };
      return byKey.get(reordered[next++]) ?? { ...c };
    });
    return rebuilt;
  }

  function moveCard(key: string, direction: -1 | 1) {
    if (layoutState === null) return;
    const movable = layoutState
      .filter((c) => !c.hidden && rendersCard(c.key)).map((c) => c.key);
    const from = movable.indexOf(key);
    const next = moveRendered(key, from + direction);
    if (next === undefined) return;
    const verb = direction === -1 ? 'up' : 'down';
    void saveLayout(next, `${cardName(key)} moved ${verb}`);
  }

  function dropCard(targetKey: string) {
    if (layoutState === null || dragKey === null || dragKey === targetKey) return;
    const movable = layoutState
      .filter((c) => !c.hidden && rendersCard(c.key)).map((c) => c.key);
    const next = moveRendered(dragKey, movable.indexOf(targetKey));
    setDragKey(null);
    setDragOverKey(null);
    if (next === undefined) return;
    void saveLayout(next, `${cardName(dragKey)} moved`);
  }

  function hideCard(key: string) {
    if (layoutState === null) return;
    focusPending.current = { kind: 'restore', key };
    void saveLayout(
      layoutState.map((c) => (c.key === key ? { ...c, hidden: true } : { ...c })),
      `${cardName(key)} hidden`,
    );
  }

  function restoreCard(key: string) {
    if (layoutState === null) return;
    focusPending.current = { kind: 'grip', key };
    void saveLayout(
      layoutState.map((c) => (c.key === key ? { ...c, hidden: false } : { ...c })),
      `${cardName(key)} restored`,
    );
  }

  function renameCard(key: string, value: string) {
    if (layoutState === null) return;
    const title = value || null; // blank means back to the default name
    focusPending.current = { kind: 'grip', key };
    setRenaming(null);
    void saveLayout(
      layoutState.map((c) => (c.key === key ? { ...c, title } : { ...c })),
      title ? `Renamed to ${title}` : `${cardName(key)} back to its default title`,
    );
  }

  // Focus lands where the last action pointed it, once the element it
  // aims at is actually on screen. A restore arms this before the
  // refetched payload has rendered the card back into the bento, so the
  // pending aim stays armed (consumed only when the element is found)
  // and the effect retries when the payload lands.
  useEffect(() => {
    const pending = focusPending.current;
    if (pending === null) return;
    const selector = pending.kind === 'restore'
      ? `[data-restore-key="${pending.key}"]`
      : `[data-grip-key="${pending.key}"]`;
    const target = document.querySelector<HTMLElement>(selector);
    if (target === null) return; // not on screen yet: stay armed
    focusPending.current = null;
    target.focus();
  }, [layoutState, data]);

  // -- the bento ----------------------------------------------------------

  const researchSpan = skillsShown ? 'span-8' : 'span-12';

  function cardNode(key: string) {
    const title = layoutTitle(key) ?? undefined;
    switch (key) {
      case 'sales':
        return (
          <SalesCard
            key={key}
            sales={data.sales}
            title={title}
            onRefetch={onRefetch}
            onExpired={onExpired}
          />
        );
      case 'commitments':
        return (
          <CommitmentsCard
            key={key}
            commitments={data.commitments}
            title={title}
            onRefetch={onRefetch}
            onExpired={onExpired}
          />
        );
      case 'research':
        return (
          <ResearchCard
            key={key}
            span={researchSpan}
            title={title}
            lastAnsweredTs={data.research.lastAnsweredTs}
            answer={answer}
            answerSeq={answerSeq}
            statusText={statusText}
          />
        );
      case 'skills':
        if (!hasSkills) return null;
        return (
          <SkillsCard
            key={key}
            skills={data.skills}
            title={title}
            busy={skillBusyId !== null}
            onRun={(id) => void runSkill(id)}
          />
        );
      default: {
        const card = data.plugins.cards.find((c) => c.id === key);
        if (!card) return null;
        return (
          <PluginCardView
            key={key}
            card={card}
            onRefetch={onRefetch}
            onExpired={onExpired}
          />
        );
      }
    }
  }

  const renderedEntries = visible.filter((entry) => rendersCard(entry.key));
  const hiddenEntries = (layoutState ?? []).filter((c) => c.hidden);

  return (
    <div className="app">
      <a className="skip-link" href="#dashboard-main">Skip to main content</a>
      <Rail inboxWaiting={data.inbox.waiting} />
      <main id="dashboard-main" tabIndex={-1}>
        <header className="hero">
          <div>
            <h1 className="hero-title">{greeting}</h1>
            <div className="hero-meta">
              <span>{dateLine}</span>
              {connected > 0 ? (
                <span className="hero-live">
                  <span className="dot" aria-hidden="true" />
                  {sourceLine}
                </span>
              ) : null}
            </div>
          </div>
          <div className="hero-actions">
            {customizing ? (
              /* One primary per surface: while customizing, Done is the
                 action; every change has already saved itself. */
              <Button tone="primary" onClick={leaveCustomize}>Done customizing</Button>
            ) : (
              <>
                {/* The wizard is a server-rendered surface: a plain form
                    post, exactly like the rendered dashboard's button. */}
                <form method="post" action="/wizard/start" className="addplugin-form">
                  <Button tone="primary" type="submit">Add plugin</Button>
                </form>
                <Button tone="secondary" onClick={() => void enterCustomize()}>Customize</Button>
              </>
            )}
          </div>
        </header>
        {!customizing && customizeNote ? (
          <p className="cust-note" role="status">{customizeNote}</p>
        ) : null}
        {customizing ? (
          <section className="cust-panel" aria-label="Customize dashboard">
            <p className="cust-hint">
              Drag a card's handle onto another card, or use the Move buttons, to
              reorder. Rename or hide from each card. Every change saves itself.
            </p>
            <p className="cust-note" role="status">{customizeNote}</p>
          </section>
        ) : null}
        <CommandBar busy={researchBusy} onAsk={ask} />
        {!customizing && statusText ? (
          <p className="research-status command-status" role="status">{statusText}</p>
        ) : null}
        {!customizing ? (
          <>
            <Brief data={data} onRefetch={onRefetch} onExpired={onExpired} />
            {answer ? (
              <section className="brief-answer" aria-label="Research answer">
                <h2>Research</h2>
                <p>{answer.summary}</p>
              </section>
            ) : null}
          </>
        ) : null}
        {customizing ? (
        <section className="bento" aria-label="Dashboard">
          {renderedEntries.map((entry, index) => {
            const node = cardNode(entry.key);
            if (node === null) return null;
            if (!customizing) return node;
            return (
              <CustomizeCell
                key={entry.key}
                cardKey={entry.key}
                name={cardName(entry.key)}
                first={index === 0}
                last={index === renderedEntries.length - 1}
                renaming={renaming === entry.key}
                dragging={dragKey === entry.key}
                dragOver={dragOverKey === entry.key}
                onRenaming={setRenaming}
                onMove={moveCard}
                onRename={renameCard}
                onHide={hideCard}
                onDragCard={(key) => setDragKey(key)}
                onDragOverCard={(key) => setDragOverKey(key)}
                onDropCard={dropCard}
                onDragEnd={() => { setDragKey(null); setDragOverKey(null); }}
              >
                {node}
              </CustomizeCell>
            );
          })}
        </section>
        ) : null}
        {customizing && hiddenEntries.length > 0 ? (
          <section className="cust-hidden" aria-label="Hidden cards">
            <div className="subhead">Hidden cards</div>
            <ul>
              {hiddenEntries.map((entry) => (
                <li key={entry.key}>
                  <span>{cardName(entry.key)}</span>
                  <button
                    type="button"
                    className="cust-btn"
                    aria-label={`Restore ${cardName(entry.key)}`}
                    data-restore-key={entry.key}
                    onClick={() => restoreCard(entry.key)}
                  >
                    Restore
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        <footer className="page-foot">
          <p>
            Nexuus Bot <span className="mono">{data.version}</span>. Workbooks are copied before they
            are read. Calendar setup stays in the browser. Research calls are logged; file contents
            stay here. <a href="/what-this-touches">What this app touches</a>
          </p>
        </footer>
      </main>
    </div>
  );
}
