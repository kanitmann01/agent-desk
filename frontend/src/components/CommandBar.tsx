// The research command bar: the centerpiece. One white well holding the
// question input and the surface's one solid-green send control. Enter
// asks, Shift+Enter gives a new line; the send control stays disabled
// until the trimmed question has a word. The sweep, the magnet pull, the
// click burst and the entrance motion are gone.
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useFaceActions } from '../face/FaceProvider';
import { useFaceActivity } from '../face/useFaceActivity';
import { ICON_SEARCH } from './EmptyState';
import { useBusy } from './useBusy';

// Five rows of the 14px field before it scrolls.
const MAX_FIELD_HEIGHT = 152;

interface CommandBarProps {
  busy: boolean;
  // True when research is off in settings: the surface states the pause
  // instead of accepting a question that cannot run.
  disabled?: boolean;
  // True when no AI key is saved: the send control becomes the link to add
  // one, and a question is kept, not sent.
  needsAi?: boolean;
  // True when the question was answered and the field should clear.
  onAsk: (question: string) => Promise<boolean>;
}

const ICON_SEND = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h13M12.5 5.5 19 12l-6.5 6.5" />
  </svg>
);

/**
 * Research command bar: the question field with the one send control.
 *
 * Enter asks and Shift+Enter inserts a newline; `onAsk` resolves true when
 * the question was answered, which is what clears the field. The send
 * control is disabled while the trimmed question is empty, so the button
 * never offers an ask that has nothing to send. A paused research source
 * disables the bar instead of accepting a question. With no AI key saved
 * (`needsAi`) the control is the link that adds one (spec 022): nothing is
 * sent until the desk can answer.
 */
export default function CommandBar({ busy, disabled = false, needsAi = false, onAsk }: CommandBarProps) {
  const [question, setQuestion] = useState('');
  const [focused, setFocused] = useState(false);
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const faceActions = useFaceActions();
  const setLookTarget = faceActions?.setLookTarget;
  const isListening = focused && !disabled;

  useFaceActivity({
    mood: 'listening',
    label: 'Listening to your question',
    active: isListening,
  });

  useEffect(() => {
    if (disabled) setFocused(false);
  }, [disabled]);

  /** Aim the face toward the center of the question field. */
  const updateLookTarget = useCallback(() => {
    if (!setLookTarget) return;
    const field = fieldRef.current;
    if (!field) {
      setLookTarget(null);
      return;
    }
    const rect = field.getBoundingClientRect();
    setLookTarget({
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    });
  }, [setLookTarget]);

  // The 100 ms gate: a fast model call never flashes a busy label. The
  // send control is disabled from the first millisecond, so a second
  // press cannot start a second ask.
  const pending = useBusy(busy);
  const sendLabel = pending ? 'Asking your AI...' : 'Research';
  const empty = question.trim() === '';

  // One-row by default, growing with the question up to five rows.
  useEffect(() => {
    const field = fieldRef.current;
    if (!field) return;
    field.style.height = 'auto';
    field.style.height = `${Math.min(field.scrollHeight, MAX_FIELD_HEIGHT)}px`;
  }, [question]);

  // Keep the face aimed at the active field across focus, blur, resize, and unmount.
  useEffect(() => {
    if (!setLookTarget) return undefined;
    if (!isListening) {
      setLookTarget(null);
      return undefined;
    }
    updateLookTarget();
    window.addEventListener('resize', updateLookTarget);
    return () => {
      window.removeEventListener('resize', updateLookTarget);
      setLookTarget(null);
    };
  }, [isListening, setLookTarget, updateLookTarget]);

  // Refresh the target center after the field resizes with typed input.
  useEffect(() => {
    if (!isListening) return;
    updateLookTarget();
  }, [isListening, question, updateLookTarget]);

  /**
   * Ask the trimmed question and clear the field when it was answered.
   *
   * The control is already disabled while the question is blank, so this
   * guard covers what the button cannot: Enter in the field, and a press
   * that lands after the bar turned busy or paused.
   */
  async function ask() {
    const trimmed = question.trim();
    if (!trimmed || busy || disabled || needsAi) return;
    const answered = await onAsk(trimmed);
    if (answered) setQuestion('');
  }

  /** Submit on Enter; Shift+Enter keeps the newline in the field. */
  function onInputKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void ask();
    }
  }

  return (
    <section className="cmd" aria-label="Ask your desk">
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
          disabled={disabled}
          onChange={(e) => setQuestion(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={onInputKey}
        />
        <span className="cmd-hint" aria-hidden="true">
          {disabled
            ? 'Research is turned off in settings.'
            : needsAi ? 'Add your AI key to ask.' : <><kbd>Enter</kbd> to ask</>}
        </span>
        <span className="cmd-magnet">
          {needsAi ? (
            <a className="cmd-send" href="/settings#ai">Connect your AI</a>
          ) : (
            <button
              className="cmd-send"
              type="button"
              aria-label={sendLabel}
              aria-busy={pending ? 'true' : undefined}
              onClick={() => void ask()}
              disabled={busy || disabled || empty}
            >
              {pending ? <span className="btn-busy-dot" aria-hidden="true" /> : null}
              <span className="btn-labels cmd-send-label">
                <span
                  className={pending ? 'btn-label btn-label-hidden' : 'btn-label'}
                  aria-hidden={pending ? 'true' : undefined}
                >
                  Research
                </span>
                <span
                  className={pending ? 'btn-label' : 'btn-label btn-label-hidden'}
                  aria-hidden={pending ? undefined : 'true'}
                >
                  Asking your AI...
                </span>
              </span>
              {ICON_SEND}
            </button>
          )}
        </span>
      </div>
    </section>
  );
}
