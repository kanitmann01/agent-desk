// The dashboard composition, driven entirely by the /api/dashboard
// payload: the rail, the hero band (the one display greeting, the date
// line, the one honest source line), the research command bar, and the
// bento grid (sales hero, commitment, research answer, skills, plugin
// cards), then the footer. The greeting and date line are computed
// client-side; the source line is only ever the truth, as on the
// server-rendered page.
import { useState } from 'react';
import { postJson } from '../api';
import { dateLineFor, greetingFor } from '../fmt';
import type { DashboardData } from '../types';
import Rail from './Rail';
import SalesCard from './SalesCard';
import CommitmentsCard from './CommitmentsCard';
import ResearchCard, { RESEARCH_BUSY, UNREACHABLE_SEND, type ResearchAnswer } from './ResearchCard';
import PluginCardView from './PluginCardView';
import SkillsCard from './SkillsCard';
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

export default function Dashboard({ data, onRefetch, onExpired }: DashboardProps) {
  // The skills strip and the research bar share one answer area and one
  // status line, exactly as the server-rendered page does.
  const [answer, setAnswer] = useState<ResearchAnswer | null>(null);
  const [answerSeq, setAnswerSeq] = useState(0);
  const [statusText, setStatusText] = useState('');
  const [skillBusyId, setSkillBusyId] = useState<number | null>(null);
  const [researchBusy, setResearchBusy] = useState(false);

  const now = new Date();
  const greeting = greetingFor(now);
  const dateLine = dateLineFor(now);
  const connected = data.sources.connected;
  const sourceLine = connected > 0
    ? `Live: ${connected} of ${data.sources.total} sources connected.`
    : 'Not connected yet: each card below has its own one-step connect.';
  // "one-step" never breaks across the line: the phrase rides in a
  // nowrap span so a narrow band wraps at the spaces around it.
  const sourceLineBody = connected > 0
    ? sourceLine
    : (
      <>
        Not connected yet: each card below has its own{' '}
        <span className="nowrap">one-step connect.</span>
      </>
    );

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

  const hasSkills = data.skills.length > 0;

  return (
    <div className="app">
      <Rail inboxWaiting={data.inbox.waiting} />
      <main>
        <header className="hero">
          <div>
            <h1 className="hero-title">{greeting}</h1>
            <div className="hero-meta">
              <span>{dateLine}</span>
              <span className="hero-live">
                <span className={connected > 0 ? 'dot' : 'dot sample'} aria-hidden="true" />
                {sourceLineBody}
              </span>
            </div>
          </div>
          <div className="hero-actions">
            {/* The wizard is a server-rendered surface: a plain form
                post, exactly like the rendered dashboard's button. */}
            <form method="post" action="/wizard/start" className="addplugin-form">
              <Button tone="primary" type="submit">Add plugin</Button>
            </form>
          </div>
        </header>
        <CommandBar busy={researchBusy} onAsk={ask} />
        <section className="bento" aria-label="Dashboard">
          <SalesCard sales={data.sales} onRefetch={onRefetch} onExpired={onExpired} />
          <CommitmentsCard commitments={data.commitments} onRefetch={onRefetch} onExpired={onExpired} />
          <ResearchCard
            span={hasSkills ? 'span-8' : 'span-12'}
            lastAnsweredTs={data.research.lastAnsweredTs}
            answer={answer}
            answerSeq={answerSeq}
            statusText={statusText}
          />
          {hasSkills && (
            <SkillsCard
              skills={data.skills}
              busy={skillBusyId !== null}
              onRun={(id) => void runSkill(id)}
            />
          )}
          {data.plugins.cards.map((card) => (
            <PluginCardView
              key={card.id}
              card={card}
              onRefetch={onRefetch}
              onExpired={onExpired}
            />
          ))}
        </section>
        <footer className="page-foot">
          <span>Agent Desk <span className="mono">{data.version}</span>.</span>
          <span>Cards show only what their connected sources report.</span>
          <a href="/what-this-touches">What this app touches</a>
        </footer>
      </main>
    </div>
  );
}
