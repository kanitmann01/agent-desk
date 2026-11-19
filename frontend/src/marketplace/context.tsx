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

/**
 * Supply the current path and navigate function to everything below it.
 *
 * The default context navigates nowhere, so a link rendered outside a provider
 * still behaves as a plain anchor.
 */
export function MarketplaceNavProvider({ value, children }: {
  value: MarketplaceNav;
  children: ReactNode;
}) {
  return <NavContext.Provider value={value}>{children}</NavContext.Provider>;
}

/** Read the nearest marketplace navigation context, or its inert default. */
export function useMarketplaceNav(): MarketplaceNav {
  return useContext(NavContext);
}

/**
 * Render a real anchor that routes plain left clicks through the client
 * router.
 *
 * Modified clicks, non-primary buttons and already-prevented events fall
 * through to the browser, so opening a new tab or copying the address still
 * does what the user expects.
 */
export function MarketLink({ to, className, children, current, ...rest }: {
  to: string;
  className?: string;
  children: ReactNode;
  current?: boolean;
  'aria-label'?: string;
}) {
  const { navigate } = useMarketplaceNav();
  /**
   * Intercept an unmodified left click and route it; leave every other event
   * to the browser's own navigation.
   */
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
