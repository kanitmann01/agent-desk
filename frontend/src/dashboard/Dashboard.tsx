// The dashboard composition, driven entirely by the /api/dashboard
// payload: the rail, the hero band (greeting, date line, the one honest
// source line), the research command bar, and the bento grid (sales
// hero, commitment, research answer, skills, plugin cards), then the
// footer. The aurora backdrop is mounted once at the root. The greeting and date line are computed
// client-side; the source line is only ever the truth, as on the
// server-rendered page.
import { useState } from 'react';
import { motion, useReducedMotion, type Variants } from 'motion/react';
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
import GlareButton from '../components/GlareButton';
import DecryptedText from '../vendor/reactbits/DecryptedText';
import GradientText from '../vendor/reactbits/GradientText';
import ShinyText from '../vendor/reactbits/ShinyText';

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

// The grid staggers its cells in; each cell carries its own spring.
const GRID_VARIANTS: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.09, delayChildren: 0.22 } },
};

export default function Dashboard({ data, onRefetch, onExpired }: DashboardProps) {
  // The skills strip and the research bar share one answer area and one
  // status line, exactly as the server-rendered page does.
  const [answer, setAnswer] = useState<ResearchAnswer | null>(null);
  const [answerSeq, setAnswerSeq] = useState(0);
  const [statusText, setStatusText] = useState('');
  const [skillBusyId, setSkillBusyId] = useState<number | null>(null);
  const [researchBusy, setResearchBusy] = useState(false);
  const reduce = useReducedMotion();

  const now = new Date();
  const greeting = greetingFor(now);
  const dateLine = dateLineFor(now);
  const connected = data.sources.connected;
  const sourceLine = connected > 0
    ? `Live: ${connected} of ${data.sources.total} sources connected.`
    : 'Not connected yet: each card below has its own one-step connect.';
  // "Good" decrypts in, the part of the day carries the gradient.
  const cut = greeting.indexOf(' ');
  const greetHead = cut > 0 ? greeting.slice(0, cut) : greeting;
  const greetTail = cut > 0 ? greeting.slice(cut + 1) : '';

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
        <motion.header
          className="hero"
          initial={reduce ? false : { opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: 'spring', stiffness: 140, damping: 20 }}
        >
          <div>
            <p className="hero-eyebrow">
              <span className="rule" aria-hidden="true" />
              Your desk, on this machine
            </p>
            <h1 className="hero-title" aria-label={greeting}>
              <DecryptedText
                text={greetHead}
                animateOn="view"
                sequential
                speed={70}
                maxIterations={12}
                scrambleColor="#4C5A55"
              />
              {greetTail ? ' ' : null}
              {greetTail ? (
                <GradientText colors={['#1F2A27', '#4C5A55']} animationSpeed={14}>
                  {greetTail}
                </GradientText>
              ) : null}
            </h1>
            <div className="hero-meta">
              <ShinyText color="#4C5A55" shineColor="#1F2A27" speed={4} delay={2.5}>
                {dateLine}
              </ShinyText>
              <span className="hero-live">
                <span className={connected > 0 ? 'dot' : 'dot sample'} aria-hidden="true" />
                <ShinyText
                  color={connected > 0 ? '#1F2A27' : '#4C5A55'}
                  shineColor="#1F2A27"
                  speed={4}
                  delay={3.5}
                  disabled={connected === 0}
                >
                  {sourceLine}
                </ShinyText>
              </span>
            </div>
          </div>
          <div className="hero-actions">
            {/* The wizard is a server-rendered surface: a plain form
                post, exactly like the rendered dashboard's button. */}
            <form method="post" action="/wizard/start" className="addplugin-form">
              <GlareButton tone="primary" type="submit">Add plugin</GlareButton>
            </form>
          </div>
        </motion.header>
        <CommandBar busy={researchBusy} onAsk={ask} />
        <motion.section
          className="bento"
          aria-label="Dashboard"
          variants={GRID_VARIANTS}
          initial="hidden"
          animate="show"
        >
          <SalesCard sales={data.sales} onRefetch={onRefetch} onExpired={onExpired} />
          <CommitmentsCard commitments={data.commitments} onRefetch={onRefetch} onExpired={onExpired} />
          <ResearchCard
            span={hasSkills ? 'span-8' : 'span-12'}
            lastAnsweredTs={data.research.lastAnsweredTs}
            answer={answer}
            answerSeq={answerSeq}
            statusText={statusText}
            busy={researchBusy || skillBusyId !== null}
          />
          {hasSkills && (
            <SkillsCard
              skills={data.skills}
              busy={skillBusyId !== null}
              onRun={(id) => void runSkill(id)}
            />
          )}
          {data.plugins.cards.map((card) => (
            <PluginCardView key={card.id} card={card} />
          ))}
        </motion.section>
        <footer className="page-foot">
          <span>Agent Desk <span className="mono">{data.version}</span>.</span>
          <span>Cards show only what their connected sources report.</span>
          <a href="/what-this-touches">What this app touches</a>
        </footer>
      </main>
    </div>
  );
}
