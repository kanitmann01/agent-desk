// Buttons with the vendored GlareHover light sweep. The wrapper only
// adds the sweep: a real button (or link) sits inside, so form
// semantics, the hit area and focus stay with the element itself.
// tone="primary" is the neon green call to action, tone="secondary" the
// quiet glass button used for Re-test and the walkthrough links.
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import GlareHover from '../vendor/reactbits/GlareHover';

type Tone = 'primary' | 'secondary';

type GlareButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> & {
  children: ReactNode;
  tone?: Tone;
  // Renders a link styled as the button instead of a button.
  href?: string;
  className?: string;
};

export default function GlareButton({ children, tone = 'secondary', href, className, disabled, ...rest }: GlareButtonProps) {
  const primary = tone === 'primary';
  return (
    <GlareHover
      background="transparent"
      borderRadius="14px"
      glareColor={primary ? '#F0FFF6' : '#7DD3FC'}
      // A disabled button keeps its place in the tree (focus is not
      // lost while a request runs) but stops answering the pointer.
      glareOpacity={disabled ? 0 : primary ? 0.5 : 0.32}
      glareAngle={-30}
      glareSize={220}
      softness={0.6}
      variant="sheen"
      mode="hover"
      rimGlint={!disabled}
      className={`glare-host ${tone}${className ? ` ${className}` : ''}`}
    >
      {href !== undefined ? (
        <a className={`btn btn-${tone}`} href={href}>{children}</a>
      ) : (
        <button type="button" className={`btn btn-${tone}`} disabled={disabled} {...rest}>
          {children}
        </button>
      )}
    </GlareHover>
  );
}
