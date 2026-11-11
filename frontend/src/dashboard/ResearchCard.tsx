// The research card: an action surface, not a data widget. The ask well,
// the honest busy line, the answer with its sources as chips, degraded
// causes stated plainly, and the last-answered stamp. Mirrors research.py
// and the research block of pages.APP_JS.
import { useState, type KeyboardEvent } from 'react';
import { postJson } from '../api';
import { hhmmFromTs } from '../fmt';
import WidgetCard from '../components/WidgetCard';

export const RESEARCH_BUSY = 'Asking the company endpoint for a sourced summary';
export const UNREACHABLE_SEND = 'The dashboard could not reach its own server; nothing was sent.';

export interface ResearchAnswer {
  question: string;
  summary: string;
  sources: string[];
}

interface ResearchCardProps {
  lastAnsweredTs: number | null;
  answer: ResearchAnswer | null;
  onAnswer: (answer: ResearchAnswer | null) => void;
  onStatus: (text: string) => void;
  statusText: string;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

interface ResearchResponse {
  status?: string;
  cause?: string;
  summary?: string;
  sources?: string[];
}

export default function ResearchCard({
  lastAnsweredTs, answer, onAnswer, onStatus, statusText, onRefetch, onExpired,
}: ResearchCardProps) {
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);

  const stamp = lastAnsweredTs !== null
    ? { fresh: true, text: `Answered ${hhmmFromTs(lastAnsweredTs)}` }
    : { fresh: true, text: 'Ready' };

  async function ask() {
    const trimmed = question.trim();
    if (!trimmed) return;
    setBusy(true);
    onStatus(RESEARCH_BUSY);
    let res;
    try {
      res = await postJson('/research', { question: trimmed });
    } catch {
      setBusy(false);
      onStatus(UNREACHABLE_SEND);
      return;
    }
    setBusy(false);
    if (res.status === 401) { onExpired(); return; }
    const data = (res.data ?? {}) as ResearchResponse;
    if (data.status === 'degraded') {
      onAnswer(null);
      onStatus(data.cause || 'The company endpoint did not answer.');
      return;
    }
    onStatus('');
    onAnswer({
      question: trimmed,
      summary: data.summary || '',
      sources: data.sources || [],
    });
    setQuestion('');
    await onRefetch(); // the stamp moves to Answered HH:MM
  }

  function onInputKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void ask();
    }
  }

  return (
    <WidgetCard
      title="Research"
      col="col-8"
      stamp={stamp}
      foot="Searches run through the company endpoint. Every call is logged: what was asked, never file contents."
    >
      <div className="well">
        <textarea
          className="well-input"
          rows={2}
          placeholder="Ask anything, or paste what you did and ask what to look for."
          aria-label="Research question"
          value={question}
          disabled={busy}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onInputKey}
        />
        <button className="btn btn-secondary" type="button" onClick={ask} disabled={busy}>
          Research
        </button>
      </div>
      {answer && (
        <div className="answer">
          <div className="aq">{answer.question}</div>
          {answer.summary}
          <div>
            {answer.sources.map((name, idx) => (
              <span className="src" key={`${name}-${idx}`}>{name}</span>
            ))}
          </div>
        </div>
      )}
      {statusText ? <p className="empty" role="status">{statusText}</p> : null}
    </WidgetCard>
  );
}
