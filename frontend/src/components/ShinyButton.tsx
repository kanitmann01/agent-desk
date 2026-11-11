// The shiny button: the vendored GlareHover (a light sweep, pure CSS)
// wrapped around a real primary button, so form semantics and focus
// stay with the button itself.
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import GlareHover from '../vendor/reactbits/GlareHover';

type ShinyButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
};

export default function ShinyButton({ children, className, ...rest }: ShinyButtonProps) {
  return (
    <GlareHover
      background="var(--primary)"
      borderRadius="8px"
      glareColor="#F6FBF9"
      glareOpacity={0.35}
      glareAngle={-30}
      glareSize={220}
      softness={0.6}
      variant="sheen"
      mode="hover"
      className={`shiny-btn${className ? ` ${className}` : ''}`}
    >
      <button type="button" className="btn btn-primary" {...rest}>
        {children}
      </button>
    </GlareHover>
  );
}
