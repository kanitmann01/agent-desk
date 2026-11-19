// The app shell: the marketplace owns /marketplace and every path under
// it; every other path is the unchanged dashboard. The shell listens for
// popstate only to cross that boundary, so browser Back from a marketplace
// page lands on the dashboard without a reload.
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { getJson, SESSION_EXPIRED_MESSAGE, SESSION_EXPIRED_TITLE } from './api';
import type { DashboardData } from './types';
import Dashboard from './dashboard/Dashboard';
import MarketplaceApp from './marketplace/MarketplaceApp';
import Button from './components/Button';

// The centered card every non-dashboard state shares. Loading is a polite
// status; a failure is an alert so the recovery is announced.
/**
 * Centered card wrapper for the shell's own messages.
 *
 * `role` picks the live-region semantics for the card and `busy` sets
 * `aria-busy`, so a wait is announced politely and a failure as an alert.
 */
function Centered({
  children,
  role,
  busy = false,
}: {
  children: ReactNode;
  role?: 'status' | 'alert';
  busy?: boolean;
}) {
  return (
    <div className="center-wrap">
      <div
        className="center-card"
        role={role}
        aria-busy={busy ? 'true' : undefined}
        aria-live={role === 'status' ? 'polite' : undefined}
      >
        {children}
      </div>
    </div>
  );
}

/** True for `/marketplace` and every path below it. */
export function isMarketplacePath(pathname: string): boolean {
  return pathname === '/marketplace' || pathname.startsWith('/marketplace/');
}

/**
 * Dashboard route: fetch `/api/dashboard` once and render the loading state,
 * the expired-session notice, a failure with retry, or the dashboard.
 */
function DashboardApp() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [expired, setExpired] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  // Focus the failure heading as it mounts (it stays out of the tab
  // order) so Try again is the following keypress. A callback ref runs
  // in the same commit as the heading, which is what the shell tests wait on.
  const focusFailure = useCallback((node: HTMLHeadingElement | null) => {
    node?.focus();
  }, []);

  const refetch = useCallback(async () => {
    const res = await getJson('/api/dashboard');
    if (res.status === 401) {
      setExpired(true);
      return;
    }
    if (!res.ok) {
      setLoadFailed(true);
      return;
    }
    setData(res.data as DashboardData);
  }, []);

  useEffect(() => {
    void refetch();
  }, [refetch]);

  if (expired) {
    return (
      <Centered role="alert">
        <h1 ref={focusFailure} tabIndex={-1}>{SESSION_EXPIRED_TITLE}</h1>
        <p>{SESSION_EXPIRED_MESSAGE}</p>
        <Button onClick={() => window.location.reload()}>Try again</Button>
      </Centered>
    );
  }

  if (!data) {
    if (loadFailed) {
      return (
        <Centered role="alert">
          <h1 ref={focusFailure} tabIndex={-1}>The dashboard did not load</h1>
          <p>The dashboard could not reach its own server. Try again; if it repeats, restart the app.</p>
          <Button onClick={() => void refetch()}>Try again</Button>
        </Centered>
      );
    }
    return (
      <Centered role="status" busy>
        <h1>Loading</h1>
        <p className="center-loader">Reading the dashboard…</p>
      </Centered>
    );
  }

  return (
    <Dashboard
      data={data}
      onRefetch={refetch}
      onExpired={() => setExpired(true)}
    />
  );
}

/**
 * Root component: pick the marketplace or the dashboard from the current
 * path, and follow `popstate` so Back leaves the marketplace without a reload.
 */
export default function App() {
  const [pathname, setPathname] = useState(() => window.location.pathname);
  useEffect(() => {
    /** Track a back/forward navigation by re-reading the current path. */
    const onPop = () => setPathname(window.location.pathname);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  if (isMarketplacePath(pathname)) return <MarketplaceApp />;
  return <DashboardApp />;
}
