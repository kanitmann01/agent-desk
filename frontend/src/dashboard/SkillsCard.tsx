// The skills strip: the user's saved asks as a slim bento cell. Each
// row runs its skill with one click (or Enter on the focused list);
// the result lands in the research answer area, as on the
// server-rendered page. Rows spring in through the vendored
// AnimatedList, drawn with this card's own row template so truncation
// and spacing match the rest of the dashboard. While a skill runs,
// further clicks are ignored, the same guard the old strip's disabled
// buttons gave.
import { motion, useReducedMotion } from 'motion/react';
import type { CSSProperties, ReactNode } from 'react';
import type { DashboardData } from '../types';
import { CELL_VARIANTS, CELL_VARIANTS_STILL } from '../components/WidgetCard';
import AnimatedList, { type AnimatedListItem } from '../vendor/reactbits/AnimatedList';
import GlassSurface from '../vendor/reactbits/GlassSurface';

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

// The list's dark theme, retinted to the dashboard palette.
const LIST_TINT = {
  '--al-tile': 'linear-gradient(180deg, rgba(255,255,255,.07) 0%, rgba(255,255,255,.035) 100%)',
  '--al-tile-edge': 'rgba(51,65,85,.6)',
  '--al-tile-highlight': 'rgba(255,255,255,.07)',
  '--al-tile-shadow': 'none',
  '--al-ink': '#F8FAFC',
  '--al-muted': '#B0BACD',
  '--al-thumb': 'rgba(148,163,184,.3)',
} as CSSProperties;

export default function SkillsCard({ skills, busy, onRun }: SkillsCardProps) {
  const reduce = useReducedMotion();
  const items: AnimatedListItem[] = skills.map((skill) => ({
    id: skill.id,
    title: skill.name,
    description: skill.description || undefined,
  }));

  return (
    <motion.div className="cell span-4" variants={reduce ? CELL_VARIANTS_STILL : CELL_VARIANTS}>
      <div className="card">
        <div className="card-body">
          <GlassSurface
            borderRadius={22.5}
            backgroundOpacity={0.05}
            refraction={false}
            renderer="svg"
            width="100%"
            height="100%"
          >
            <section className="widget" aria-label="Your skills">
              <div className="w-head">
                <h2>Your skills</h2>
                <span className="stamp">{skills.length} saved</span>
              </div>
              <div className="w-body">
                <AnimatedList
                  className="skills-list"
                  itemClassName="skill-item"
                  items={items}
                  renderItem={SkillRow}
                  onItemSelect={(_item, index) => {
                    if (!busy) onRun(skills[index].id);
                  }}
                  frame={false}
                  theme="dark"
                  accentColor="#22C55E"
                  radius={12}
                  gap={8}
                  width="100%"
                  maxHeight={264}
                  fadeSize={20}
                  displayScrollbar={false}
                  style={LIST_TINT}
                />
              </div>
              <div className="w-foot">Click one to run it; the result lands in Research.</div>
            </section>
          </GlassSurface>
        </div>
      </div>
    </motion.div>
  );
}
