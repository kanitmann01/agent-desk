// The skills strip: the user's saved asks as a slim bento cell. Each
// row runs its skill with one click (or Enter on the focused list);
// the result lands in the research answer area, as on the
// server-rendered page. Rows spring in through the vendored
// AnimatedList. While a skill runs, further clicks are ignored, the
// same guard the old strip's disabled buttons gave.
import { motion, useReducedMotion } from 'motion/react';
import type { CSSProperties } from 'react';
import type { DashboardData } from '../types';
import { CELL_VARIANTS, CELL_VARIANTS_STILL } from '../components/WidgetCard';
import AnimatedList, { type AnimatedListItem } from '../vendor/reactbits/AnimatedList';
import GlassSurface from '../vendor/reactbits/GlassSurface';

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
  '--al-muted': '#94A3B8',
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
              <AnimatedList
                className="skills-list"
                items={items}
                onItemSelect={(_item, index) => {
                  if (!busy) onRun(skills[index].id);
                }}
                frame={false}
                theme="dark"
                accentColor="#22C55E"
                radius={12}
                gap={6}
                width="100%"
                maxHeight={228}
                fadeSize={28}
                displayScrollbar={false}
                style={LIST_TINT}
              />
              <div className="w-foot">One click runs the saved ask; the result lands in Research.</div>
            </section>
          </GlassSurface>
        </div>
      </div>
    </motion.div>
  );
}
