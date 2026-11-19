// Buttons on the system: one solid-green primary per surface, the
// quiet white secondary. The element is the control itself (no
// wrapper), so form semantics, the hit area and focus stay with it.
import type { ButtonHTMLAttributes, ReactNode } from 'react';

type Tone = 'primary' | 'secondary';

type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> & {
  children: ReactNode;
  tone?: Tone;
  // Renders a link styled as the button instead of a button.
  href?: string;
  className?: string;
};

/**
 * Button for the desk's surfaces: primary is the one solid-green action,
 * secondary the quiet one.
 *
 * `href` renders an anchor styled as the button; every other prop goes to
 * the button element, so form and ARIA semantics stay with the caller.
 */
export default function Button({ children, tone = 'secondary', href, className, disabled, ...rest }: ButtonProps) {
  const cls = `btn btn-${tone}${className ? ` ${className}` : ''}`;
  if (href !== undefined) {
    return <a className={cls} href={href}>{children}</a>;
  }
  return (
    <button type="button" className={cls} disabled={disabled} {...rest}>
      {children}
    </button>
  );
}
