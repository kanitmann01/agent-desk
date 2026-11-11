// TextType, Agent Desk flavor. The reactbits component of the same name
// drives its cursor through GSAP, which sits outside this repo's
// permissive license allowlist (MIT, Apache-2.0, BSD, ISC), so the same
// effect (text that types itself out behind a blinking bar cursor) is
// built here on plain React timers instead. The whole text is in the
// DOM from the first frame for assistive tech, the part not typed yet
// holds its layout invisibly so the card never jumps while typing, and
// prefers-reduced-motion shows the final text at once.
import { useEffect, useMemo, useState } from 'react';
import { useReducedMotion } from 'motion/react';

export interface TextTypeProps {
  text: string;
  className?: string;
  // Milliseconds between ticks.
  typingSpeed?: number;
  // Upper bound for the whole reveal: long answers type several
  // characters per tick so nobody waits on the effect.
  maxDuration?: number;
  initialDelay?: number;
  showCursor?: boolean;
}

export default function TextType({
  text,
  className,
  typingSpeed = 18,
  maxDuration = 2400,
  initialDelay = 0,
  showCursor = true,
}: TextTypeProps) {
  const reduce = useReducedMotion();
  const chars = useMemo(() => Array.from(text), [text]);
  const [count, setCount] = useState(() => (reduce ? chars.length : 0));

  useEffect(() => {
    if (reduce) {
      setCount(chars.length);
      return undefined;
    }
    setCount(0);
    const ticks = Math.max(1, Math.floor(maxDuration / Math.max(1, typingSpeed)));
    const stride = Math.max(1, Math.ceil(chars.length / ticks));
    let shown = 0;
    let interval = 0;
    const start = window.setTimeout(() => {
      interval = window.setInterval(() => {
        shown = Math.min(chars.length, shown + stride);
        setCount(shown);
        if (shown >= chars.length) window.clearInterval(interval);
      }, typingSpeed);
    }, initialDelay);
    return () => {
      window.clearTimeout(start);
      window.clearInterval(interval);
    };
  }, [chars, reduce, typingSpeed, maxDuration, initialDelay]);

  const done = count >= chars.length;

  return (
    <span className={className}>
      <span className="sr-only">{text}</span>
      <span aria-hidden="true">
        {chars.slice(0, count).join('')}
        {showCursor && !done ? <span className="tt-cursor" /> : null}
        {done ? null : <span className="tt-rest">{chars.slice(count).join('')}</span>}
      </span>
    </span>
  );
}
