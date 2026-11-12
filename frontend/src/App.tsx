// The app shell: one fetch of /api/dashboard, the honest session-expired
// view on a 401, and the dashboard once the payload is in. While the
// payload loads the vendored LatticeLoader holds the screen.
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { getJson, SESSION_EXPIRED_MESSAGE, SESSION_EXPIRED_TITLE } from './api';
import type { DashboardData } from './types';
import Dashboard from './dashboard/Dashboard';
import GlareButton from './components/GlareButton';
import LatticeLoader from './vendor/reactbits/LatticeLoader';

// The centered card every non-dashboard state shares; the backdrop
// behind it is mounted once, at the root.
function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="center-wrap">
      <div className="center-card">{children}</div>
    </div>
  );
}

export default function App() {
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
        <GlareButton onClick={() => window.location.reload()}>Try again</GlareButton>
      </Centered>
    );
  }

  if (!data) {
    if (loadFailed) {
      return (
        <Centered>
          <h1>The dashboard did not load</h1>
          <p>The dashboard could not reach its own server. Try again; if it repeats, restart the app.</p>
          <GlareButton onClick={() => void refetch()}>Try again</GlareButton>
        </Centered>
      );
    }
    return (
      <Centered>
        <h1>Loading</h1>
        <div className="center-loader">
          <LatticeLoader
            label="Reading the dashboard."
            pattern="orbit"
            color="#14594E"
            cellSize={5}
            gap={2}
            fontSize={13.5}
            showTimer={false}
            glow
          />
        </div>
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
