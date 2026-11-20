// The skills strip: the user's saved asks as a slim bento cell. Each
// row runs its skill with one click (or Enter on the focused button);
// the result lands in the research answer area, as on the
// server-rendered page. While a skill runs, further clicks are
// ignored.
import type { ReactNode } from 'react';
import type { DashboardData } from '../types';
import WidgetCard from '../components/WidgetCard';

const ICON_RUN = (
  <svg className="skill-go" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M9 6.5 14.5 12 9 17.5" />
  </svg>
);

/** One saved ask, as a row that runs it; clicks are ignored while a skill runs. */
function SkillRow({ skill, busy, onRun }: { skill: DashboardData['skills'][number]; busy: boolean; onRun: (id: number) => void }): ReactNode {
  return (
    <li>
      <button
        className="skill-item"
        type="button"
        onClick={() => {
          if (!busy) onRun(skill.id);
        }}
        aria-label={`Run ${skill.name}`}
      >
        <span className="skill-text">
          <span className="skill-name">{skill.name}</span>
          {skill.description ? <span className="skill-desc">{skill.description}</span> : null}
        </span>
        {ICON_RUN}
      </button>
    </li>
  );
}

interface SkillsCardProps {
  skills: DashboardData['skills'];
  // The layout's custom title, when the user renamed the card.
  title?: string;
  busy: boolean;
  onRun: (id: number) => void;
}

/**
 * The saved asks as a slim card whose rows run their skill into the research answer
 * area.
 *
 * busy holds off further runs while one is in flight.
 */
export default function SkillsCard({ skills, title, busy, onRun }: SkillsCardProps) {
  return (
    <WidgetCard
      title={title ?? 'Your skills'}
      span="span-4"
      stamp={{ fresh: true, text: `${skills.length} saved` }}
      menuItems={[{ label: 'Open settings', href: '/settings' }]}
      foot="Click one to run it; the result lands in Research."
    >
      <ul className="skills-list">
        {skills.map((skill) => (
          <SkillRow key={skill.id} skill={skill} busy={busy} onRun={onRun} />
        ))}
      </ul>
    </WidgetCard>
  );
}
