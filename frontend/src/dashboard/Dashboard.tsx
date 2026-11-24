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
import CustomizeCell, { type CustomizePending } from './CustomizeCell';
import Brief from './Brief';
import CommandBar from '../components/CommandBar';
import Button from '../components/Button';
import { PhaseText, useAnnouncement, usePhase } from '../components/feedback';
import { useBusy } from '../components/useBusy';
import { PendingBody } from './pending';

interface DashboardProps {
  data: DashboardData;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
  /** A quiet line for a poll that could not reach the desk. */
  pollNote?: string;
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
  error?: string;
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

const SAVE_UNREACHABLE = 'The dashboard could not reach its own server; the layout was not saved. Try again.';
const SAVE_REFUSED = 'The layout was not saved; the dashboard re-read the saved layout. Try again.';
const SETUP_DISMISSED_KEY = 'agentdesk.setupDismissed';

// The one layout save in flight, and the control that started it, so the
// control carries its own continuous verb while the panel holds the rest.
type LayoutAction = 'move-up' | 'move-down' | 'move' | 'hide' | 'restore' | 'rename';
interface LayoutPending {
  key: string;
  action: LayoutAction;
  pendingNote: string;
  doneNote: string;
  // The typed title to restore when a rename save failed (F5).
  renameValue?: string;
}

/** True when the Get started strip was hidden earlier in this sitting. */
function storedSetupDismissed(): boolean {
  try {
    return sessionStorage.getItem(SETUP_DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * The composed dashboard: rail, hero, research bar, bento grid and footer, in the
 * layout's saved order.
 *
 * Customize mode wraps every visible card in its toolbar and saves each change as it
 * happens, so leaving the mode loses nothing. onRefetch reloads the payload; onExpired
 * hands a 401 back to the caller.
 */
export default function Dashboard({ data, onRefetch, onExpired, pollNote = '' }: DashboardProps) {
  // The skills strip and the research bar share one answer area and one
  // failure line, exactly as the server-rendered page does.
  const [answer, setAnswer] = useState<ResearchAnswer | null>(null);
  const [answerSeq, setAnswerSeq] = useState(0);
  const [answerError, setAnswerError] = useState('');
  const [skillBusyId, setSkillBusyId] = useState<number | null>(null);
  const [researchBusy, setResearchBusy] = useState(false);
  const answerBusy = researchBusy || skillBusyId !== null;
  const answerPhase = researchBusy ? RESEARCH_BUSY : 'Running the saved ask';
  // The answer's own box is reserved while the placeholder is up, so the
  // real answer replaces it in place. Nothing shows under 100 ms.
  const answerPending = usePhase(answerBusy, answerPhase);
  // A sheet that closed mid-request still reports its outcome here.
  const liveOutcome = useAnnouncement();

  // Customize mode: the full layout (hidden cards included) lives here,
  // read from /api/layout on entering and kept in step with every save.
  const [customizing, setCustomizing] = useState(false);
  const [layoutState, setLayoutState] = useState<LayoutCardState[] | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState<string | null>(null);
  const [customizeNote, setCustomizeNote] = useState('');
  const [customizeBusy, setCustomizeBusy] = useState(false);
  const [openingCustomize, setOpeningCustomize] = useState(false);
  const [layoutBusy, setLayoutBusy] = useState(false);
  const [layoutPending, setLayoutPending] = useState<{ key: string; action: CustomizePending } | null>(null);
  // The control that started a layout save is inert at once; its pending
  // verb and aria-busy wait out the 100 ms gate (F1), and its phase line
  // owns the ten-second honesty rule (F4) on a slow disk.
  const layoutPendingShown = useBusy(layoutBusy);
  const layoutPhase = usePhase(layoutBusy, customizeNote);
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [dragOverKey, setDragOverKey] = useState<string | null>(null);
  // Nothing shows under 100 ms: the Customize control and the panel both
  // wait out the same gate before they show the opening.
  const customizeOpening = usePhase(customizeBusy, 'customize-open');
  // The Get started strip: "Not now" hides it for this sitting only (the
  // key lives in session storage), so the desk asks again tomorrow until
  // the three steps are done.
  const [setupDismissed, setSetupDismissed] = useState(storedSetupDismissed);
  // True once Finish setup is clicked, until the strip is back and focused.
  const focusSetup = useRef(false);
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
  // The setup steps are the server's (spec 022): the strip renders while
  // one is open, and the AI is connected when the source table says so.
  const setupSteps = data.setup?.steps ?? [];
  const setupOpen = setupSteps.filter((step) => !step.done).length;
  const aiConnected = data.sources.items.some(
    (item) => item.id === 'research-endpoint' && item.status === 'connected',
  );

  /** Hide the Get started strip for this sitting. */
  function dismissSetup() {
    setSetupDismissed(true);
    try {
      sessionStorage.setItem(SETUP_DISMISSED_KEY, '1');
    } catch {
      // Storage unavailable (private mode): hidden until the page reloads.
    }
  }

  /** Bring the Get started strip back and move focus onto it. */
  function showSetup() {
    focusSetup.current = true;
    setSetupDismissed(false);
    try {
      sessionStorage.removeItem(SETUP_DISMISSED_KEY);
    } catch {
      // Storage unavailable: the state above still shows the strip.
    }
  }

  useEffect(() => {
    if (!focusSetup.current || setupDismissed) return;
    const strip = document.getElementById('get-started');
    if (strip === null) return; // not on screen yet: stay armed
    focusSetup.current = false;
    strip.focus();
  }, [setupDismissed, data]);

  // The layout the payload carries: visible cards only, in render
  // order, custom titles riding along.
  const visible = data.layout.cards;
  const hasSkills = data.skills.length > 0;
  // The skills card renders only when the layout shows it AND there are
  // skills to list; a card with nothing honest to say is not a card.
  const skillsShown = visible.some((c) => c.key === 'skills') && hasSkills;

  /**
   * The custom title for a layout key, from the customize copy first and the payload
   * second; null keeps the default.
   */
  function layoutTitle(key: string): string | null {
    const fromState = layoutState?.find((c) => c.key === key);
    if (fromState) return fromState.title;
    return visible.find((c) => c.key === key)?.title ?? null;
  }

  /**
   * The name a card is labelled with: its custom title, its default title, or the
   * plugin's own.
   */
  function cardName(key: string): string {
    const plugin = data.plugins.cards.find((c) => c.id === key);
    return layoutTitle(key) ?? DEFAULT_CARD_TITLES[key] ?? plugin?.title ?? key;
  }

  // Does this layout key render a card at all right now? (The skills
  // card needs skills; a plugin key needs its installed card.)
  /**
   * True when this layout key has something to render now: the skills card needs
   * skills, a plugin key its installed card.
   */
  function rendersCard(key: string): boolean {
    if (key === 'skills') return hasSkills;
    if (!(key in DEFAULT_CARD_TITLES)) {
      return data.plugins.cards.some((c) => c.id === key);
    }
    return true;
  }

  /**
   * Show a research answer, bumping the sequence so the block remounts even for a
   * repeated question.
   */
  function showAnswer(next: ResearchAnswer | null) {
    setAnswer(next);
    setAnswerSeq((seq) => seq + 1);
  }

  /**
   * Ask the research endpoint and show the answer, or its degraded cause; true when an
   * answer arrived.
   *
   * A 401 goes to onExpired, and an answer refetches so the stamp moves to its answered
   * time.
   */
  async function ask(question: string): Promise<boolean> {
    setResearchBusy(true);
    setAnswerError('');
    let res;
    try {
      res = await postJson('/research', { question });
    } catch {
      setResearchBusy(false);
      setAnswerError(`${UNREACHABLE_SEND} Try again.`);
      return false;
    }
    setResearchBusy(false);
    if (res.status === 401) { onExpired(); return false; }
    const d = (res.data ?? {}) as ResearchResponse;
    if (!res.ok) {
      // A refused request is not an empty answer: say the server's
      // sentence in the answer area and keep the question.
      showAnswer(null);
      setAnswerError(d.error || 'Your AI did not answer. Try again in a moment.');
      return false;
    }
    if (d.status === 'degraded') {
      showAnswer(null);
      setAnswerError(d.cause || 'Your AI did not answer. Try again in a moment.');
      return false;
    }
    setAnswerError('');
    showAnswer({
      question,
      summary: d.summary || '',
      sources: d.sources || [],
    });
    void onRefetch(); // the stamp moves to Answered HH:MM
    return true;
  }

  /** Run a saved ask and show its result in the shared answer area. */
  async function runSkill(id: number) {
    setSkillBusyId(id);
    setAnswerError('');
    let res;
    try {
      res = await postJson(`/skills/${id}/run`);
    } catch {
      setSkillBusyId(null);
      setAnswerError('The dashboard could not reach its own server; nothing was sent. Try again.');
      return;
    }
    setSkillBusyId(null);
    if (res.status === 401) { onExpired(); return; }
    const d = (res.data ?? {}) as SkillResponse;
    if (d.status === 'ok') {
      setAnswerError('');
      showAnswer({
        question: 'Skill result',
        summary: d.summary || d.reply || '',
        sources: [],
      });
      return;
    }
    showAnswer(null);
    setAnswerError(d.cause || 'The saved ask did not finish. Try again in a moment.');
  }

  // -- customize mode ---------------------------------------------------

  // The layout read, guarded like every other call the cards make: a
  // rejected fetch answers null (the server is unreachable) instead of
  // escaping as an unhandled rejection.
  /**
   * The layout payload from /api/layout, or null when the server could not be reached.
   */
  async function readLayout() {
    try {
      return await getJson('/api/layout');
    } catch {
      return null;
    }
  }

  /** Open customize mode on the full saved layout, hidden cards included. */
  async function enterCustomize() {
    setCustomizeBusy(true);
    setOpeningCustomize(true);
    setCustomizeNote('');
    const res = await readLayout();
    setCustomizeBusy(false);
    if (res !== null && res.status === 401) {
      setOpeningCustomize(false);
      onExpired();
      return;
    }
    if (res === null) {
      setOpeningCustomize(false);
      setCustomizeNote('The dashboard could not reach its own server; customize did not open. Try again.');
      return;
    }
    if (!res.ok) {
      setOpeningCustomize(false);
      setCustomizeNote('The dashboard could not read the layout; customize did not open. Try again.');
      return;
    }
    const d = (res.data ?? {}) as { cards?: LayoutCardState[] };
    setLayoutState(Array.isArray(d.cards) ? d.cards : []);
    setCustomizeNote('');
    setRenaming(null);
    setRenameDraft(null);
    setCustomizing(true);
    setOpeningCustomize(false);
  }

  /**
   * Close customize mode and drop its transient state; every change saved itself
   * already.
   */
  function leaveCustomize() {
    setCustomizing(false);
    setOpeningCustomize(false);
    setRenaming(null);
    setRenameDraft(null);
    setDragKey(null);
    setDragOverKey(null);
    setCustomizeNote('');
  }

  /**
   * Re-read the saved layout and the payload, so the screen shows only what the server
   * holds.
   */
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
  /**
   * Save the whole layout and show the note; a refused save re-reads the server's copy
   * instead.
   *
   * The arrangement is applied before the POST, so the screen answers the click at
   * once, and it is replaced by the saved one when the POST fails. The control that
   * started the save carries its pending verb until the fresh payload lands, and a
   * failed rename reopens its editor with the typed title.
   */
  async function saveLayout(next: LayoutCardState[], pending: LayoutPending): Promise<boolean> {
    setLayoutState(next);
    setLayoutBusy(true);
    setLayoutPending({ key: pending.key, action: pending.action });
    setCustomizeNote(pending.pendingNote);
    let res;
    try {
      res = await postJson('/api/layout', { cards: next });
    } catch {
      res = null;
    }
    if (res !== null && res.status === 401) {
      setLayoutBusy(false);
      setLayoutPending(null);
      onExpired();
      return false;
    }
    if (res === null || !res.ok) {
      setCustomizeNote(res === null ? SAVE_UNREACHABLE : SAVE_REFUSED);
      if (pending.action === 'rename') {
        setRenameDraft(pending.renameValue ?? '');
        setRenaming(pending.key);
      }
      setLayoutBusy(false);
      setLayoutPending(null);
      await resyncLayout();
      return false;
    }
    const d = (res.data ?? {}) as { cards?: LayoutCardState[] };
    setLayoutState(Array.isArray(d.cards) ? d.cards : next);
    await onRefetch();
    setLayoutBusy(false);
    setLayoutPending(null);
    setCustomizeNote(pending.doneNote);
    return true;
  }

  // Reorder within the sequence of cards that actually render; hidden
  // and empty cards keep their slots around them.
  /**
   * The layout with one rendered card moved among the cards that render, or undefined
   * when the card cannot move.
   *
   * Hidden and empty cards keep their slots around it.
   */
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

  /** Move a rendered card one place up or down and save the layout. */
  function moveCard(key: string, direction: -1 | 1) {
    if (layoutState === null || layoutBusy) return;
    const movable = layoutState
      .filter((c) => !c.hidden && rendersCard(c.key)).map((c) => c.key);
    const from = movable.indexOf(key);
    const next = moveRendered(key, from + direction);
    if (next === undefined) return;
    const verb = direction === -1 ? 'up' : 'down';
    void saveLayout(next, {
      key,
      action: direction === -1 ? 'move-up' : 'move-down',
      pendingNote: `Moving ${cardName(key)} ${verb}...`,
      doneNote: `${cardName(key)} moved ${verb}`,
    });
  }

  /** Move the dragged card onto a target card and save the layout. */
  function dropCard(targetKey: string) {
    if (layoutState === null || dragKey === null || dragKey === targetKey || layoutBusy) return;
    const moving = dragKey;
    const movable = layoutState
      .filter((c) => !c.hidden && rendersCard(c.key)).map((c) => c.key);
    const next = moveRendered(moving, movable.indexOf(targetKey));
    setDragKey(null);
    setDragOverKey(null);
    if (next === undefined) return;
    void saveLayout(next, {
      key: moving,
      action: 'move',
      pendingNote: `Moving ${cardName(moving)}...`,
      doneNote: `${cardName(moving)} moved`,
    });
  }

  /** Hide a card and save the layout, aiming focus at its Restore button. */
  function hideCard(key: string) {
    if (layoutState === null || layoutBusy) return;
    focusPending.current = { kind: 'restore', key };
    void saveLayout(
      layoutState.map((c) => (c.key === key ? { ...c, hidden: true } : { ...c })),
      {
        key,
        action: 'hide',
        pendingNote: `Hiding ${cardName(key)}...`,
        doneNote: `${cardName(key)} hidden`,
      },
    );
  }

  /** Restore a hidden card and save the layout, aiming focus at its grip. */
  function restoreCard(key: string) {
    if (layoutState === null || layoutBusy) return;
    focusPending.current = { kind: 'grip', key };
    void saveLayout(
      layoutState.map((c) => (c.key === key ? { ...c, hidden: false } : { ...c })),
      {
        key,
        action: 'restore',
        pendingNote: `Restoring ${cardName(key)}...`,
        doneNote: `${cardName(key)} restored`,
      },
    );
  }

  /**
   * Set a card's custom title and save the layout; a blank value returns it to the
   * default name.
   */
  function renameCard(key: string, value: string) {
    if (layoutState === null || layoutBusy) return;
    const title = value || null; // blank means back to the default name
    void (async () => {
      const saved = await saveLayout(
        layoutState.map((c) => (c.key === key ? { ...c, title } : { ...c })),
        {
          key,
          action: 'rename',
          pendingNote: title ? `Saving the new title for ${cardName(key)}...` : `Saving ${cardName(key)}'s default title...`,
          doneNote: title ? `Renamed to ${title}` : `${cardName(key)} back to its default title`,
          renameValue: value,
        },
      );
      if (!saved) return;
      // The editor stays open while the save runs (the Save title control
      // carries the wait); it closes only once the new title is on disk.
      setRenaming(null);
      setRenameDraft(null);
      document.querySelector<HTMLElement>(`[data-grip-key="${key}"]`)?.focus();
    })();
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

  /**
   * The card element for a layout key, or null when the key names nothing that renders
   * right now.
   */
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
            enabled={data.research.enabled}
            lastAnsweredTs={data.research.lastAnsweredTs}
            answer={answer}
            answerSeq={answerSeq}
            busy={answerBusy}
            busyPhase={answerPhase}
            error={answerError}
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
            busyId={skillBusyId}
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
  // A card being restored stays in the strip until its save answers, so the
  // Restore control can carry its own pending state instead of vanishing.
  const hiddenEntries = (layoutState ?? []).filter((c) =>
    c.hidden || (layoutPending?.key === c.key && layoutPending.action === 'restore'));

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
                {/* The plugin wizard lives on the Plugins page (spec 022);
                    Customize stays because it is the only place the
                    commitment check-off, source re-test and skill-run
                    controls exist. */}
                {setupDismissed && setupOpen > 0 ? (
                  <button
                    type="button"
                    className="text-btn finish-setup"
                    aria-label={`Finish setup, ${setupOpen} ${setupOpen === 1 ? 'step' : 'steps'} left`}
                    onClick={showSetup}
                  >
                    Finish setup
                  </button>
                ) : null}
                <Button
                  tone="secondary"
                  onClick={() => void enterCustomize()}
                  disabled={customizeBusy}
                  pending={customizeOpening.shown}
                  pendingLabel="Opening..."
                >
                  Customize
                </Button>
              </>
            )}
          </div>
        </header>
        {liveOutcome ? (
          <p className="page-status" role="status">{liveOutcome}</p>
        ) : null}
        {pollNote ? (
          <p className="poll-note" role="status">{pollNote}</p>
        ) : null}
        {!customizing && customizeNote ? (
          <p className="cust-note" role="status">{customizeNote}</p>
        ) : null}
        {(customizing || (openingCustomize && customizeOpening.shown)) ? (
          <section
            className="cust-panel"
            aria-label="Customize dashboard"
            aria-busy={customizing ? undefined : 'true'}
          >
            {customizing ? (
              <>
                <p className="cust-hint">
                  Drag a card's handle onto another card, or use the Move buttons, to
                  reorder. Rename or hide from each card. Every change saves itself.
                </p>
                <p className="cust-note" role="status">
                  {layoutBusy
                    ? (layoutPhase.shown ? <PhaseText text={customizeNote} slow={layoutPhase.slow} /> : null)
                    : customizeNote}
                </p>
              </>
            ) : (
              <>
                <div className="wire-lines cust-panel-wire" aria-hidden="true">
                  <span style={{ width: '92%' }} />
                  <span style={{ width: '64%' }} />
                </div>
                <p className="phase-line" role="status">
                  <span className="btn-busy-dot" aria-hidden="true" />
                  <span>
                    <PhaseText text="Reading your saved layout" slow={customizeOpening.slow} />
                  </span>
                </p>
              </>
            )}
          </section>
        ) : null}
        <CommandBar busy={researchBusy} disabled={!data.research.enabled} needsAi={!aiConnected} onAsk={ask} />
        {!customizing ? (
          <>
            <Brief
              data={data}
              onRefetch={onRefetch}
              onExpired={onExpired}
              setupDismissed={setupDismissed}
              onDismissSetup={dismissSetup}
              skillBusyId={skillBusyId}
              onRunSkill={(id) => void runSkill(id)}
            />
            {visible.some((card) => card.key === 'research')
              && (answer || answerPending.shown || answerError) ? (
              <section className="brief-answer" aria-label="Research answer">
                <h2>{layoutTitle('research') ?? 'Research'}</h2>
                {answerPending.shown ? (
                  <PendingBody
                    phase={answerPhase}
                    slow={answerPending.slow}
                    lines={4}
                    className="brief-answer-copy"
                  />
                ) : answerError ? (
                  <p className="alert" role="alert">{answerError}</p>
                ) : (
                  <p className="brief-answer-copy" role="status">{answer?.summary}</p>
                )}
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
                renameValue={renaming === entry.key ? renameDraft : null}
                dragging={dragKey === entry.key}
                dragOver={dragOverKey === entry.key}
                busy={layoutBusy}
                pending={layoutPending?.key === entry.key ? layoutPending.action : null}
                pendingShown={layoutPending?.key === entry.key && layoutPendingShown}
                onRenaming={(key) => {
                  setRenameDraft(null);
                  setRenaming(key);
                }}
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
              {hiddenEntries.map((entry) => {
                const restoring = layoutPending?.key === entry.key && layoutPending.action === 'restore';
                // The control is inert at once; its pending verb and
                // aria-busy wait out the 100 ms gate.
                const restoringShown = restoring && layoutPendingShown;
                return (
                  <li key={entry.key}>
                    <span>{cardName(entry.key)}</span>
                    {restoring ? (
                      <button
                        type="button"
                        className="cust-btn"
                        disabled
                        aria-busy={restoringShown ? 'true' : undefined}
                        aria-label={restoringShown
                          ? `Restoring ${cardName(entry.key)}...`
                          : `Restore ${cardName(entry.key)}`}
                        data-restore-key={entry.key}
                      >
                        <span
                          className={restoringShown ? 'btn-busy-dot' : 'btn-busy-dot busy-hidden'}
                          aria-hidden="true"
                        />
                        <span className="btn-labels">
                          <span
                            className={restoringShown ? 'btn-label btn-label-hidden' : 'btn-label'}
                            aria-hidden={restoringShown ? 'true' : undefined}
                          >
                            Restore
                          </span>
                          <span
                            className={restoringShown ? 'btn-label' : 'btn-label btn-label-hidden'}
                            aria-hidden={restoringShown ? undefined : 'true'}
                          >
                            Restoring...
                          </span>
                        </span>
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="cust-btn"
                        aria-label={`Restore ${cardName(entry.key)}`}
                        data-restore-key={entry.key}
                        disabled={layoutBusy}
                        onClick={() => restoreCard(entry.key)}
                      >
                        Restore
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}
        <footer className="page-foot">
          <p>
            Agent Desk <span className="mono">{data.version}</span>. Workbooks are copied before they
            are read. Calendar setup stays in the browser. Research calls are logged; file contents
            stay here. <a href="/what-this-touches">What this app touches</a>
          </p>
        </footer>
      </main>
    </div>
  );
}
