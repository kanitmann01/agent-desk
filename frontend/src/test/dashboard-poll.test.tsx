// The screen listens (spec 023): the dashboard re-reads /api/dashboard
// every 8 seconds while the tab is visible and pauses while it is
// hidden, the Memory island's own pattern. The pins ride fake timers
// and a counted fetch stub, so no test waits on a real clock, and the
// hidden case proves the pause rather than a slow server. A read that
// cannot reach the server leaves the last screen up, and a slow earlier
// read never overwrites a newer payload.
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import App from '../App';
import type { DashboardData } from '../types';

const DATA: DashboardData = {
  version: '0.0.0-test',
  flags: { excelEnabled: false, calendarEnabled: false, endpointEnabled: false },
  sources: { connected: 0, total: 3, items: [] },
  sales: { enabled: true, mode: 'unconfigured', status: null },
  commitments: { enabled: true, mode: 'unavailable', status: null },
  research: { enabled: true, lastAnsweredTs: null },
  inbox: { waiting: 0 },
  agentLoop: { lastRunTs: null, nextRunTs: null, enabled: true },
  skills: [],
  layout: {
    cards: [
      { key: 'sales', title: null },
      { key: 'commitments', title: null },
      { key: 'research', title: null },
      { key: 'skills', title: null },
    ],
  },
  plugins: { cards: [] },
};

/** A promise a test resolves by hand, so a response can land out of order. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

/** The stubbed fetch calls that went to the dashboard payload. */
function dashboardFetches(fetchMock: ReturnType<typeof vi.fn>): unknown[] {
  return fetchMock.mock.calls.filter(([url]) => String(url) === '/api/dashboard');
}

/** Render the shell over the stub and let the mount fetch land. */
async function mount(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock);
  render(<App />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

it('re-reads the payload every 8 seconds while the tab is visible', async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn(async () => Response.json(DATA));
  await mount(fetchMock);
  // The mount fetch is the first; each 8-second tick adds exactly one.
  expect(dashboardFetches(fetchMock)).toHaveLength(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(8000);
  });
  expect(dashboardFetches(fetchMock)).toHaveLength(2);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(24000);
  });
  expect(dashboardFetches(fetchMock)).toHaveLength(5);
});

it('pauses while the tab is hidden and resumes when it is visible again', async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn(async () => Response.json(DATA));
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
  await mount(fetchMock);
  // The mount fetch ran; four hidden ticks change nothing.
  expect(dashboardFetches(fetchMock)).toHaveLength(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(32000);
  });
  expect(dashboardFetches(fetchMock)).toHaveLength(1);
  visibility.mockReturnValue('visible');
  await act(async () => {
    await vi.advanceTimersByTimeAsync(8000);
  });
  expect(dashboardFetches(fetchMock)).toHaveLength(2);
});

it('leaves the last screen up when a poll cannot reach the server', async () => {
  vi.useFakeTimers();
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  const unhandled: unknown[] = [];
  /** Collect a promise nobody handled: the failure mode this test pins. */
  const onUnhandled = (reason: unknown) => {
    unhandled.push(reason);
  };
  process.on('unhandledRejection', onUnhandled);
  let reads = 0;
  const fetchMock = vi.fn((url: string) => {
    // The view report is a POST of its own; only the payload read fails.
    if (String(url) !== '/api/dashboard') return Promise.resolve(Response.json({}));
    reads += 1;
    return reads === 1
      ? Promise.resolve(Response.json(DATA))
      : Promise.reject(new TypeError('Failed to fetch'));
  });
  try {
    await mount(fetchMock);
    // The mount read landed and the dashboard owns the screen.
    expect(screen.getByRole('link', { name: 'Inbox' })).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
    // The rejected tick changed nothing: the banner, not a failure card,
    // and the next tick still runs on the same cadence.
    expect(dashboardFetches(fetchMock)).toHaveLength(2);
    expect(screen.getByRole('link', { name: 'Inbox' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /did not load/i })).toBeNull();
    expect(consoleError).not.toHaveBeenCalled();
    expect(unhandled).toEqual([]);
  } finally {
    process.off('unhandledRejection', onUnhandled);
  }
});

it('drops a stale response instead of overwriting a newer payload', async () => {
  vi.useFakeTimers();
  const firstTick = deferred<Response>();
  const secondTick = deferred<Response>();
  let reads = 0;
  const fetchMock = vi.fn((url: string) => {
    if (String(url) !== '/api/dashboard') return Promise.resolve(Response.json({}));
    reads += 1;
    if (reads === 1) return Promise.resolve(Response.json(DATA));
    return reads === 2 ? firstTick.promise : secondTick.promise;
  });
  await mount(fetchMock);
  // Two ticks overlap: the first read is still in flight when the second
  // starts, which is what a slow server produces on an 8-second cadence.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(8000);
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(8000);
  });
  expect(dashboardFetches(fetchMock)).toHaveLength(3);
  // The newer read lands first and paints its payload.
  await act(async () => {
    secondTick.resolve(Response.json({ ...DATA, inbox: { waiting: 2 } }));
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(screen.getByRole('link', { name: 'Inbox, 2 waiting' })).toBeInTheDocument();
  // The older read lands late and must not roll the screen back.
  await act(async () => {
    firstTick.resolve(Response.json({ ...DATA, inbox: { waiting: 9 } }));
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(screen.getByRole('link', { name: 'Inbox, 2 waiting' })).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Inbox, 9 waiting' })).toBeNull();
});
