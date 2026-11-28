// The app shell: the marketplace owns /marketplace and every path under
// it; every other path is the unchanged dashboard. The shell listens for
// popstate only to cross that boundary, so browser Back from a marketplace
// page lands on the dashboard without a reload.
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { getJson, postJson, SESSION_EXPIRED_MESSAGE, SESSION_EXPIRED_TITLE } from './api';
import type { DashboardData, InsightBlock, PluginCard } from './types';
import Dashboard from './dashboard/Dashboard';
import DashboardSkeleton from './dashboard/DashboardSkeleton';
import MarketplaceApp from './marketplace/MarketplaceApp';
import Button from './components/Button';
import { FaceProvider } from './face/FaceProvider';

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
function isMarketplacePath(pathname: string): boolean {
  return pathname === '/marketplace' || pathname.startsWith('/marketplace/');
}

// The desk acts on its own now (spec 023), so the dashboard re-reads the
// payload on a cadence instead of waiting for a click: every 8 seconds
// while the tab is visible, paused while it is hidden, the Memory
// island's own pattern. A changed payload re-renders the bento; no
// socket, no event stream, no new dependency.
const POLL_MS = 8000;

// The sitting's delta lines (spec 033): the SPA reports the view once per
// sitting, so every poll that follows answers without the delta block. Each
// tile's first-seen line is held here against a signature of the tile's
// other content, so the line stays up while the reader reads it, and goes
// (or is replaced by the answer's newer line) once the content changes.
interface SittingDelta {
  signature: string;
  block: InsightBlock | null;
}

/** A tile's content signature: the payload with every delta block stripped,
 * so the delta line itself never counts as a change. */
function cardContentSignature(card: PluginCard): string {
  const payload = card.payload;
  if (!payload) return 'null';
  const insight = payload.insight;
  if (!insight?.blocks) return JSON.stringify(payload);
  return JSON.stringify({
    ...payload,
    insight: { ...insight, blocks: insight.blocks.filter((block) => block.kind !== 'delta') },
  });
}

/**
 * Fold the sitting's delta lines into a freshly read payload, which reaches
 * the screen only through this fold.
 *
 * A poll whose tile content stands still keeps the line the sitting opened
 * with; a changed tile clears it or adopts the newer line the answer
 * brought. Cards that left the layout drop their held line.
 */
function applySittingDeltas(data: DashboardData, held: Map<string, SittingDelta>): DashboardData {
  const seen = new Set<string>();
  for (const card of data.plugins.cards) {
    seen.add(card.id);
    const incoming = card.payload?.insight?.blocks?.find((block) => block.kind === 'delta') ?? null;
    const signature = cardContentSignature(card);
    const sitting = held.get(card.id);
    if (!sitting || sitting.signature !== signature) {
      held.set(card.id, { signature, block: incoming });
      continue;
    }
    sitting.block = incoming ?? sitting.block;
    const insight = card.payload?.insight;
    if (!incoming && sitting.block && insight) {
      insight.blocks = [sitting.block, ...(insight.blocks ?? [])];
    }
  }
  for (const id of held.keys()) {
    if (!seen.has(id)) held.delete(id);
  }
  return data;
}

/**
 * Dashboard route: fetch `/api/dashboard` on mount and then, while the tab
 * is visible, every POLL_MS, and render the loading state, the
 * expired-session notice, a failure with retry, or the dashboard.
 */
function DashboardApp() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [expired, setExpired] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  // A failed tick after the first payload is quiet, not a failure card:
  // the last reading stays up and one muted line says why (F6).
  const [pollFailed, setPollFailed] = useState(false);
  // The view report is a POST, so it must fire once per mount, after the
  // first successful load, and never make rendering wait for it.
  const reportedView = useRef(false);
  // One increasing number per read. A response that comes back after a
  // newer read was started is stale: it belongs to a payload the screen
  // has already moved past, so it is dropped instead of overwriting it.
  const latestRead = useRef(0);
  // Each tile's sitting delta, held across the polls that no longer carry
  // it (see applySittingDeltas).
  const sittingDeltas = useRef(new Map<string, SittingDelta>());

  // Focus the failure heading as it mounts (it stays out of the tab
  // order) so Try again is the following keypress. A callback ref runs
  // in the same commit as the heading, which is what the shell tests wait on.
  const focusFailure = useCallback((node: HTMLHeadingElement | null) => {
    node?.focus();
  }, []);

  const refetch = useCallback(async () => {
    const read = ++latestRead.current;
    try {
      const res = await getJson('/api/dashboard');
      if (read !== latestRead.current) return;
      if (res.status === 401) {
        setExpired(true);
        return;
      }
      if (!res.ok) {
        setLoadFailed(true);
        setPollFailed(true);
        return;
      }
      setData(applySittingDeltas(res.data as DashboardData, sittingDeltas.current));
      setLoadFailed(false);
      setPollFailed(false);
      if (!reportedView.current) {
        reportedView.current = true;
        void postJson('/api/dashboard/view').catch(() => {});
      }
    } catch {
      // A tick that cannot reach the server (offline, a dropped
      // connection) is not a user action: the last good screen stays up,
      // and one quiet line says the reading is the last one. The next
      // tick tries again.
      setPollFailed(true);
    }
  }, []);

  useEffect(() => {
    void refetch();
  }, [refetch]);

  // The screen listens (spec 023): a pass that lands while the user
  // reads shows up on the next tick, without a click. Hidden tabs
  // pause; the tick after returning picks the change up.
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refetch();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [refetch]);

  if (expired) {
    return (
      <Centered role="alert">
        <h1 ref={focusFailure} tabIndex={-1}>{SESSION_EXPIRED_TITLE}</h1>
        <p>{SESSION_EXPIRED_MESSAGE}</p>
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
    return <DashboardSkeleton />;
  }

  return (
    <Dashboard
      data={data}
      onRefetch={refetch}
      onExpired={() => setExpired(true)}
      pollNote={pollFailed
        ? 'The desk could not be reached just now. Showing the last reading; the next check tries again.'
        : ''}
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
  return (
    <FaceProvider>
      {isMarketplacePath(pathname) ? <MarketplaceApp /> : <DashboardApp />}
    </FaceProvider>
  );
}
