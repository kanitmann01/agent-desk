// The research answer area: an action surface, not a data widget. The
// question is asked from the command bar above the grid; this card
// shows the honest busy line, the answer typing itself out with its
// sources as chips, degraded causes stated plainly, and the
// last-answered stamp. Mirrors research.py and the research block of
// pages.APP_JS; the skills strip shares this answer area and status line.
import { motion, useReducedMotion } from 'motion/react';
import { hhmmFromTs } from '../fmt';
import WidgetCard, { type CardSpan } from '../components/WidgetCard';
import LatticeLoader from '../vendor/reactbits/LatticeLoader';
import TextType from '../vendor/reactbits/TextType';

export const RESEARCH_BUSY = 'Asking the company endpoint for a sourced summary';
export const UNREACHABLE_SEND = 'The dashboard could not reach its own server; nothing was sent.';

export interface ResearchAnswer {
  question: string;
  summary: string;
  sources: string[];
}

interface ResearchCardProps {
  span: CardSpan;
  lastAnsweredTs: number | null;
  answer: ResearchAnswer | null;
  // Bumps on every new answer so the reveal restarts even when the same
  // question is asked twice.
  answerSeq: number;
  statusText: string;
  busy: boolean;
}

const ICON_IDLE = (
  <svg className="idle-mark" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="11" cy="11" r="6.5" />
    <path d="m16 16 4.5 4.5" />
  </svg>
);

export default function ResearchCard({
  span, lastAnsweredTs, answer, answerSeq, statusText, busy,
}: ResearchCardProps) {
  const reduce = useReducedMotion();
  const stamp = lastAnsweredTs !== null
    ? { fresh: true, text: `Answered ${hhmmFromTs(lastAnsweredTs)}` }
    : { fresh: true, text: 'Ready' };

  return (
    <WidgetCard
      title="Research"
      span={span}
      stamp={stamp}
      foot="Searches run through the company endpoint. Every call is logged: what was asked, never file contents."
    >
      {answer && (
        <motion.div
          key={answerSeq}
          className="answer"
          initial={reduce ? false : { opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: 'spring', stiffness: 170, damping: 20 }}
        >
          <div className="aq">{answer.question}</div>
          <TextType text={answer.summary} />
          <div>
            {answer.sources.map((name, idx) => (
              <motion.span
                className="src"
                key={`${name}-${idx}`}
                initial={reduce ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5 + idx * 0.07, duration: 0.3 }}
              >
                {name}
              </motion.span>
            ))}
          </div>
        </motion.div>
      )}
      {/* While a request runs the vendored loader carries the status
          line (it is its own live region); afterwards the plain status
          paragraph states the outcome, as before. */}
      {statusText && busy ? (
        <div className="research-status">
          <LatticeLoader
            label={statusText}
            pattern="orbit"
            color="#22D3EE"
            cellSize={4}
            gap={2}
            fontSize={13}
            showTimer={false}
            glow
          />
        </div>
      ) : null}
      {statusText && !busy ? (
        <p className="research-status" role="status">{statusText}</p>
      ) : null}
      {!answer && !statusText ? (
        <p className="research-idle">
          {ICON_IDLE}
          <span>No answer yet. Ask from the bar above and the sourced summary lands here.</span>
        </p>
      ) : null}
    </WidgetCard>
  );
}
