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
  // Shows the control working: a busy dot, the pending verb and no second
  // press. The idle label stays in the layout, hidden, so the box holds.
  pending?: boolean;
  // The continuous verb while pending; defaults to the normal label.
  pendingLabel?: string;
};

/**
 * Button for the desk's surfaces: primary is the one solid-green action,
 * secondary the quiet one.
 *
 * `href` renders an anchor styled as the button; every other prop goes to
 * the button element, so form and ARIA semantics stay with the caller.
 * `pending` applies to the button element: a link navigates, it does not
 * work, so it has no pending state.
 */
export default function Button({
  children,
  tone = 'secondary',
  href,
  className,
  disabled,
  pending = false,
  pendingLabel,
  ...rest
}: ButtonProps) {
  const cls = `btn btn-${tone}${className ? ` ${className}` : ''}`;
  if (href !== undefined) {
    return <a className={cls} href={href}>{children}</a>;
  }
  if (pending) {
    return (
      <button
        type="button"
        className={`${cls} btn-pending`}
        disabled={disabled || pending}
        {...rest}
        aria-busy="true"
      >
        <span className="btn-busy-dot" aria-hidden="true" />
        <span className="btn-labels">
          <span className="btn-label btn-label-hidden" aria-hidden="true">{children}</span>
          <span className="btn-label">{pendingLabel ?? children}</span>
        </span>
      </button>
    );
  }
  return (
    <button type="button" className={cls} disabled={disabled} {...rest}>
      {children}
    </button>
  );
}
