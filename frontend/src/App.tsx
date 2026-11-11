// The app shell: one fetch of /api/dashboard, the honest session-expired
// view on a 401, and the dashboard once the payload is in.
import { useCallback, useEffect, useState } from 'react';
import { getJson, SESSION_EXPIRED_MESSAGE, SESSION_EXPIRED_TITLE } from './api';
import type { DashboardData } from './types';
import Dashboard from './dashboard/Dashboard';

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
      <div className="error-card">
        <h1>{SESSION_EXPIRED_TITLE}</h1>
        <p>{SESSION_EXPIRED_MESSAGE}</p>
        <p><button className="btn btn-secondary" type="button" onClick={() => window.location.reload()}>
          Try again
        </button></p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="error-card">
        <h1>{loadFailed ? 'The dashboard did not load' : 'Loading'}</h1>
        <p>
          {loadFailed
            ? 'The dashboard could not reach its own server. Try again; if it repeats, restart the app.'
            : 'Reading the dashboard.'}
        </p>
        {loadFailed && (
          <p><button className="btn btn-secondary" type="button" onClick={() => void refetch()}>
            Try again
          </button></p>
        )}
      </div>
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
