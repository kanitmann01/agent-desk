// The research command bar: the centerpiece. One white well holding the
// question input and the surface's one solid-green send control. Enter
// asks, Shift+Enter gives a new line. Behavior mirrors the old ask well
// exactly; the sweep, the magnet pull, the click burst and the entrance
// motion are gone.
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ICON_SEARCH } from './EmptyState';

// Five rows of the 14px field before it scrolls.
const MAX_FIELD_HEIGHT = 152;

interface CommandBarProps {
  busy: boolean;
  // True when research is off in settings: the surface states the pause
  // instead of accepting a question that cannot run.
  disabled?: boolean;
  // True when the question was answered and the field should clear.
  onAsk: (question: string) => Promise<boolean>;
}

const ICON_SEND = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h13M12.5 5.5 19 12l-6.5 6.5" />
  </svg>
);

export default function CommandBar({ busy, disabled = false, onAsk }: CommandBarProps) {
  const [question, setQuestion] = useState('');
  const fieldRef = useRef<HTMLTextAreaElement>(null);

  // One-row by default, growing with the question up to five rows.
  useEffect(() => {
    const field = fieldRef.current;
    if (!field) return;
    field.style.height = 'auto';
    field.style.height = `${Math.min(field.scrollHeight, MAX_FIELD_HEIGHT)}px`;
  }, [question]);

  async function ask() {
    const trimmed = question.trim();
    if (!trimmed || busy || disabled) return;
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
    <section className="cmd" aria-label="Ask the company endpoint">
      <div className="cmd-inner">
        <span className="cmd-icon" aria-hidden="true">{ICON_SEARCH}</span>
        <textarea
          ref={fieldRef}
          className="cmd-field"
          name="question"
          rows={1}
          placeholder="Ask anything, or paste what you did and ask what to look for."
          aria-label="Research question"
          autoComplete="off"
          value={question}
          disabled={busy || disabled}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onInputKey}
        />
        <span className="cmd-hint" aria-hidden="true">
          {disabled ? 'Research is turned off in settings.' : <><kbd>Enter</kbd> to ask</>}
        </span>
        <span className="cmd-magnet">
          <button className="cmd-send" type="button" aria-label="Research" onClick={() => void ask()} disabled={busy || disabled}>
            <span className="cmd-send-label">Research</span> {ICON_SEND}
          </button>
        </span>
      </div>
    </section>
  );
}
