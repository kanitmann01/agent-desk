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

// The centered card every non-dashboard state shares.
function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="center-wrap">
      <div className="center-card">{children}</div>
    </div>
  );
}

export function isMarketplacePath(pathname: string): boolean {
  return pathname === '/marketplace' || pathname.startsWith('/marketplace/');
}

function DashboardApp() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [expired, setExpired] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

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
      <Centered>
        <h1>{SESSION_EXPIRED_TITLE}</h1>
        <p>{SESSION_EXPIRED_MESSAGE}</p>
        <Button onClick={() => window.location.reload()}>Try again</Button>
      </Centered>
    );
  }

  if (!data) {
    if (loadFailed) {
      return (
        <Centered>
          <h1>The dashboard did not load</h1>
          <p>The dashboard could not reach its own server. Try again; if it repeats, restart the app.</p>
          <Button onClick={() => void refetch()}>Try again</Button>
        </Centered>
      );
    }
    return (
      <Centered>
        <h1>Loading</h1>
        <p className="center-loader">Reading the dashboard.</p>
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

export default function App() {
  const [pathname, setPathname] = useState(() => window.location.pathname);
  useEffect(() => {
    const onPop = () => setPathname(window.location.pathname);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  if (isMarketplacePath(pathname)) return <MarketplaceApp />;
  return <DashboardApp />;
}
