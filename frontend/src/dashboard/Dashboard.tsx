// The dashboard composition: rail, greeting, source banner, skills
// strip, cards and footer, driven entirely by the /api/dashboard
// payload. The greeting and date line are computed client-side; the one
// source line is only ever the truth, as on the server-rendered page.
import { useState } from 'react';
import { postJson } from '../api';
import { dateLineFor, greetingFor } from '../fmt';
import type { DashboardData } from '../types';
import Rail from './Rail';
import SalesCard from './SalesCard';
import CommitmentsCard from './CommitmentsCard';
import ResearchCard, { type ResearchAnswer } from './ResearchCard';
import PluginCardView from './PluginCardView';
import SplitText from '../vendor/reactbits/SplitText';

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

export default function Dashboard({ data, onRefetch, onExpired }: DashboardProps) {
  // The skills strip and the research card share one answer area and one
  // status line, exactly as the server-rendered page does.
  const [answer, setAnswer] = useState<ResearchAnswer | null>(null);
  const [statusText, setStatusText] = useState('');
  const [skillBusyId, setSkillBusyId] = useState<number | null>(null);

  const now = new Date();
  const greeting = greetingFor(now);
  const dateLine = dateLineFor(now);
  const connected = data.sources.connected;
  const sourceLine = connected > 0
    ? `Live: ${connected} of ${data.sources.total} sources connected.`
    : 'Not connected yet: each card below has its own one-step connect.';

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
    setAnswer({
      question: d.status === 'ok' ? 'Skill result' : 'Skill unavailable',
      summary: d.status === 'ok' ? (d.summary || d.reply || '') : (d.cause || ''),
      sources: [],
    });
  }

  return (
    <div className="app">
      <Rail inboxWaiting={data.inbox.waiting} />
      <main>
        <div className="topbar">
          <div>
            <h1>
              <SplitText text={greeting} />
            </h1>
            <p className="sub">
              <span className={connected > 0 ? 'dot' : 'dot sample'} aria-hidden="true" />
              {dateLine} {sourceLine}
            </p>
          </div>
          {/* The wizard is a server-rendered surface: a plain form post,
              exactly like the rendered dashboard's button. */}
          <form method="post" action="/wizard/start" className="addplugin-form">
            <button className="btn btn-primary" type="submit">Add plugin</button>
          </form>
        </div>
        {data.skills.length > 0 && (
          <div className="skills-strip" aria-label="Your skills">
            {data.skills.map((skill) => (
              <button
                key={skill.id}
                className="skill-btn"
                type="button"
                disabled={skillBusyId !== null}
                onClick={() => runSkill(skill.id)}
              >
                {skill.name}
              </button>
            ))}
          </div>
        )}
        <section className="grid" aria-label="Dashboard">
          <SalesCard sales={data.sales} onRefetch={onRefetch} onExpired={onExpired} />
          <CommitmentsCard commitments={data.commitments} onRefetch={onRefetch} onExpired={onExpired} />
          <ResearchCard
            lastAnsweredTs={data.research.lastAnsweredTs}
            answer={answer}
            onAnswer={setAnswer}
            statusText={statusText}
            onStatus={setStatusText}
            onRefetch={onRefetch}
            onExpired={onExpired}
          />
          {data.plugins.cards.map((card) => (
            <PluginCardView key={card.id} card={card} />
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
