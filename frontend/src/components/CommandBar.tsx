// The research command bar: the centerpiece. One white well holding the
// question input and the surface's one solid-green send control. Enter
// asks, Shift+Enter gives a new line. Behavior mirrors the old ask well
// exactly; the sweep, the magnet pull and the click burst are gone.
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { motion, useReducedMotion } from 'motion/react';

// Five rows of the 15.5px field before it scrolls.
const MAX_FIELD_HEIGHT = 152;

interface CommandBarProps {
  busy: boolean;
  // True when the question was answered and the field should clear.
  onAsk: (question: string) => Promise<boolean>;
}

const ICON_SPARK = (
  <span className="cmd-icon" aria-hidden="true">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z" />
      <path d="M19 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" />
    </svg>
  </span>
);

const ICON_SEND = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h13M12.5 5.5 19 12l-6.5 6.5" />
  </svg>
);

export default function CommandBar({ busy, onAsk }: CommandBarProps) {
  const [question, setQuestion] = useState('');
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const reduce = useReducedMotion();

  // One-row by default, growing with the question up to five rows.
  useEffect(() => {
    const field = fieldRef.current;
    if (!field) return;
    field.style.height = 'auto';
    field.style.height = `${Math.min(field.scrollHeight, MAX_FIELD_HEIGHT)}px`;
  }, [question]);

  async function ask() {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    const answered = await onAsk(trimmed);
    if (answered) setQuestion('');
  }

  function onInputKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void ask();
    }
  }

  return (
    <motion.section
      className="cmd"
      aria-label="Ask the company endpoint"
      initial={reduce ? false : { opacity: 0, y: 18, scale: 0.985 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: 'spring', stiffness: 150, damping: 19, delay: 0.12 }}
    >
      <div className="cmd-inner">
        {ICON_SPARK}
        <textarea
          ref={fieldRef}
          className="cmd-field"
          rows={1}
          placeholder="Ask anything, or paste what you did and ask what to look for."
          aria-label="Research question"
          value={question}
          disabled={busy}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onInputKey}
        />
        <span className="cmd-hint" aria-hidden="true">
          <kbd>Enter</kbd> to ask
        </span>
        <span className="cmd-magnet">
          <button className="cmd-send" type="button" onClick={() => void ask()} disabled={busy}>
            Research {ICON_SEND}
          </button>
        </span>
      </div>
    </motion.section>
  );
}
