// The marketplace's navigation context and the one link component every
// surface uses. Links stay real anchors (keyboard, copy address) and only
// intercept unmodified left clicks so the router, not the server, moves.
import { createContext, useContext, type MouseEvent, type ReactNode } from 'react';

interface MarketplaceNav {
  path: string;
  navigate: (to: string, replace?: boolean) => void;
}

const NavContext = createContext<MarketplaceNav>({
  path: '/marketplace',
  navigate: () => {},
});

export function MarketplaceNavProvider({ value, children }: {
  value: MarketplaceNav;
  children: ReactNode;
}) {
  return <NavContext.Provider value={value}>{children}</NavContext.Provider>;
}

export function useMarketplaceNav(): MarketplaceNav {
  return useContext(NavContext);
}

export function MarketLink({ to, className, children, current, ...rest }: {
  to: string;
  className?: string;
  children: ReactNode;
  current?: boolean;
  'aria-label'?: string;
}) {
  const { navigate } = useMarketplaceNav();
  function onClick(event: MouseEvent<HTMLAnchorElement>) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey
        || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(to);
  }
  return (
    <a
      href={to}
      className={className}
      onClick={onClick}
      aria-current={current ? 'page' : undefined}
      {...rest}
    >
      {children}
    </a>
  );
}
