// The screen listens (spec 023): the dashboard re-reads /api/dashboard
// every 8 seconds while the tab is visible and pauses while it is
// hidden, the Memory island's own pattern. The pins ride fake timers
// and a counted fetch stub, so no test waits on a real clock, and the
// hidden case proves the pause rather than a slow server.
import { act, cleanup, render } from '@testing-library/react';
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
  layout: { cards: [] },
  plugins: { cards: [] },
};

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
