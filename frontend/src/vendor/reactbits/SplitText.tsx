// SplitText, Agent Desk flavor. The reactbits component of the same name
// animates through GSAP, which sits outside this repo's permissive
// license allowlist (MIT, Apache-2.0, BSD, ISC), so the same effect (a
// greeting that rises in word by word, once, subtly) is built here on
// motion (MIT) instead. Honors prefers-reduced-motion by rendering the
// text whole.
import { motion, useReducedMotion } from 'motion/react';

export interface SplitTextProps {
  text: string;
  className?: string;
  delay?: number;
  stagger?: number;
}

export default function SplitText({ text, className, delay = 0, stagger = 0.03 }: SplitTextProps) {
  const reduce = useReducedMotion();
  if (reduce) {
    return <span className={className}>{text}</span>;
  }
  const words = text.split(' ');
  return (
    <span className={className} aria-label={text}>
      {words.map((word, index) => (
        <motion.span
          key={`${word}-${index}`}
          aria-hidden="true"
          style={{ display: 'inline-block', whiteSpace: 'pre' }}
          initial={{ opacity: 0, y: '0.35em' }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: delay + index * stagger, ease: 'easeOut' }}
        >
          {word}
          {index < words.length - 1 ? ' ' : ''}
        </motion.span>
      ))}
    </span>
  );
}
