// The skills strip: the user's saved asks as a slim bento cell. Each
// row runs its skill with one click (or Enter on the focused list);
// the result lands in the research answer area, as on the
// server-rendered page. Rows spring in through the vendored
// AnimatedList, drawn with the shared row template so truncation and
// spacing match the rest of the dashboard. While a skill runs, further
// clicks are ignored, the same guard the old strip's disabled buttons
// gave.
import type { CSSProperties, ReactNode } from 'react';
import type { DashboardData } from '../types';
import WidgetCard from '../components/WidgetCard';
import AnimatedList, { type AnimatedListItem } from '../vendor/reactbits/AnimatedList';

const ICON_RUN = (
  <svg className="skill-go" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M9 6.5 14.5 12 9 17.5" />
  </svg>
);

function SkillRow(item: AnimatedListItem): ReactNode {
  const entry = item !== null && typeof item === 'object' ? item : { title: item };
  return (
    <>
      <span className="skill-text">
        <span className="skill-name">{entry.title}</span>
        {entry.description ? <span className="skill-desc">{entry.description}</span> : null}
      </span>
      {ICON_RUN}
    </>
  );
}

interface SkillsCardProps {
  skills: DashboardData['skills'];
  busy: boolean;
  onRun: (id: number) => void;
}

// The list tile, retinted to the system: quiet white rows on the card,
// hairline edges, ink text.
const LIST_TINT = {
  '--al-tile': 'transparent',
  '--al-tile-edge': 'var(--hairline)',
  '--al-tile-highlight': 'transparent',
  '--al-tile-shadow': 'none',
  '--al-ink': '#1F2A27',
  '--al-muted': '#4C5A55',
  '--al-thumb': 'rgba(169,177,172,.4)',
} as CSSProperties;

export default function SkillsCard({ skills, busy, onRun }: SkillsCardProps) {
  const items: AnimatedListItem[] = skills.map((skill) => ({
    id: skill.id,
    title: skill.name,
    description: skill.description || undefined,
  }));

  return (
    <WidgetCard
      title="Your skills"
      span="span-4"
      stamp={{ fresh: true, text: `${skills.length} saved` }}
      foot="Click one to run it; the result lands in Research."
    >
      <AnimatedList
        className="skills-list"
        itemClassName="skill-item"
        items={items}
        renderItem={SkillRow}
        onItemSelect={(_item, index) => {
          if (!busy) onRun(skills[index].id);
        }}
        frame={false}
        theme="light"
        accentColor="#14594E"
        radius={6}
        gap={8}
        width="100%"
        maxHeight={264}
        fadeSize={20}
        displayScrollbar={false}
        style={LIST_TINT}
      />
    </WidgetCard>
  );
}
