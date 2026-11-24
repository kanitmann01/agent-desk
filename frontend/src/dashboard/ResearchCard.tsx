// The research answer area: an action surface, not a data widget. The
// question is asked from the command bar above the grid; this card
// shows the honest busy line, the answer with its sources as chips,
// degraded causes stated plainly, and the last-answered stamp. Mirrors
// research.py and the research block of pages.APP_JS; the skills strip
// shares this answer area and status line.
import { hhmmFromTs } from '../fmt';
import WidgetCard, { type CardSpan } from '../components/WidgetCard';
import EmptyState, { ICON_SEARCH } from '../components/EmptyState';

export const RESEARCH_BUSY = 'Asking your AI for a sourced summary';
export const UNREACHABLE_SEND = 'The dashboard could not reach its own server; nothing was sent.';

export interface ResearchAnswer {
  question: string;
  summary: string;
  sources: string[];
}

interface ResearchCardProps {
  span: CardSpan;
  // The layout's custom title, when the user renamed the card.
  title?: string;
  // The payload's research.enabled: when off, the card states the pause
  // honestly instead of offering an ask surface that cannot run.
  enabled: boolean;
  lastAnsweredTs: number | null;
  answer: ResearchAnswer | null;
  // Bumps on every new answer so the block remounts even when the same
  // question is asked twice.
  answerSeq: number;
  // The honest status line: the busy ask and every failure cause state
  // themselves in plain text.
  statusText: string;
}

/**
  * The research answer area: the question asked, its sourced summary, the status line
  * and the last-answered stamp.
 *
  * span sets the card's width in the layout; answerSeq keys the answer block so asking
  * the same question twice still remounts it.
 */
export default function ResearchCard({
  span, title, enabled, lastAnsweredTs, answer, answerSeq, statusText,
}: ResearchCardProps) {
  const stamp = !enabled
    ? { fresh: false, text: 'Paused' }
    : lastAnsweredTs !== null
      ? { fresh: true, text: `Answered ${hhmmFromTs(lastAnsweredTs)}` }
      : { fresh: true, text: 'Ready' };

  return (
    <WidgetCard
      title={title ?? 'Research'}
      span={span}
      sparse={!answer}
      stamp={stamp}
      menuItems={[{ label: 'Open settings', href: '/settings' }]}
      foot="Searches run through your AI. Every call is logged: what was asked, never file contents."
    >
      {answer && (
        <div className="answer" key={answerSeq}>
          <div className="aq">{answer.question}</div>
          <p>{answer.summary}</p>
          <div>
            {answer.sources.map((name, idx) => (
              <span className="src" key={`${name}-${idx}`}>{name}</span>
            ))}
          </div>
        </div>
      )}
      {!enabled ? (
        <p className="empty" data-research-disabled>
          Research is turned off in settings. <a href="/settings">Turn it back on</a>.
        </p>
      ) : null}
      {enabled && statusText ? (
        <p className="research-status" role="status">{statusText}</p>
      ) : null}
      {enabled && !answer && !statusText ? (
        <EmptyState icon={ICON_SEARCH}>
          No answer yet. Ask from the bar above and the sourced summary lands here.
        </EmptyState>
      ) : null}
    </WidgetCard>
  );
}
