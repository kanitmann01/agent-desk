// Spec 027, the dashboard and the shell: every wait the reader starts
// says so on the control that started it, the region that will receive
// the result shows its shape, a failure is said in place, and the first
// load is the bento's own geometry. Fake timers pin the 100 ms gate and
// the ten-second honesty line; the rest runs on real timers so the
// rendered result is the one a person sees.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import Dashboard from '../dashboard/Dashboard';
import Brief from '../dashboard/Brief';
import PluginCardView from '../dashboard/PluginCardView';
import SalesCard from '../dashboard/SalesCard';
import CommitmentsCard from '../dashboard/CommitmentsCard';
import TrackerCard from '../dashboard/TrackerCard';
import type {
  DashboardData,
  LayoutCardState,
  PluginCard,
  Recommendation,
  SalesStatus,
} from '../types';

const NOOP = () => {};
const NOOP_REFETCH = async () => {};

const DATA: DashboardData = {
  version: '0.0.0-test',
  flags: { excelEnabled: true, calendarEnabled: true, endpointEnabled: true },
  sources: {
    connected: 1,
    total: 3,
    items: [{ id: 'research-endpoint', status: 'connected', detail: 'AI connected.' }],
  },
  sales: { enabled: true, mode: 'unconfigured', status: null },
  commitments: { enabled: true, mode: 'unavailable', status: null },
  research: { enabled: true, lastAnsweredTs: null },
  inbox: { waiting: 0 },
  skills: [],
  layout: {
    cards: [
      { key: 'sales', title: null },
      { key: 'commitments', title: null },
      { key: 'research', title: null },
    ],
  },
  plugins: { cards: [] },
};

const LAYOUT: LayoutCardState[] = [
  { key: 'sales', hidden: false, title: null },
  { key: 'commitments', hidden: false, title: null },
  { key: 'research', hidden: false, title: null },
  { key: 'skills', hidden: false, title: null },
];

const SKILL_DATA: DashboardData = {
  ...DATA,
  skills: [{ id: 1, name: 'Monday numbers', description: 'Summarize the sheet' }],
  layout: {
    cards: [
      { key: 'research', title: null },
      { key: 'skills', title: null },
    ],
  },
};

const RECOMMENDATION: Recommendation = {
  cardId: 'card-1',
  title: 'Halvorsen Freight: December 15',
  why: 'You told the desk this deadline.',
  whySource: 'rule',
  score: null,
  due: '2026-12-15',
  href: '/agents',
  actionLabel: 'Open Agents',
  sample: false,
  cites: [],
};

const HEALTHY_SALES: SalesStatus = {
  configured: true,
  state: 'healthy',
  path: 'C:/desk/sales.xlsx',
  delta: { added: [['East', 10]], removed: [] },
  rowsSeen: 12,
  last_ok_ts: 1700000000,
};

const COMMITMENTS_HEALTHY = {
  state: 'healthy',
  keyEvent: {
    id: 'evt-1',
    subject: 'Q4 review',
    start: '2026-11-24T10:00:00',
    end: '2026-11-24T11:00:00',
    location: 'Room 2',
    attendees: 3,
  },
  breakdown: { subtasks: ['Prepare the numbers'], followups: [] },
  checks: {},
  firstDetected: '2026-11-24T08:00:00',
  generatedAt: '2026-11-24T09:00:00',
};

const TRACKER_CARD: PluginCard = {
  id: 'excel-report~q4',
  title: 'Q4 bookings',
  version: '0.1.0',
  pilot: false,
  state: 'enabled',
  freshness: 'fresh',
  cause: '',
  payload: {
    tracker: {
      name: 'Q4 bookings', value: '12,400', unit: 'GBP', delta: '-8%', direction: 'down',
      points: [12, 11, 10, 9], file: 'reports/q4.xlsx',
    },
    elements: [],
    insight: {
      status: 'ok',
      source: 'local',
      note: '',
      blocks: [],
      press: {
        label: 'Explain this range',
        route: '/api/insight/draft',
        kind: 'explain-range',
        text: 'Booked is 18 rows behind last month.',
      },
    },
  },
};

const DIGEST_CARD: PluginCard = {
  id: 'outlook-digest',
  title: 'Outlook Brief',
  version: '0.3.0',
  pilot: false,
  state: 'enabled',
  freshness: 'fresh',
  cause: '',
  payload: {
    elements: [{ kind: 'text', label: 'Reading', text: 'The Q4 forecast is waiting on you.' }],
    insight: {
      status: 'ok',
      source: 'local',
      note: '',
      press: {
        label: 'Draft the reply',
        route: '/api/insight/draft',
        kind: 'reply-draft',
        thread: { subject: 'Q4 forecast', sender: 'Dana Whitfield' },
      },
      blocks: [],
    },
  },
};

const DRAFT = {
  status: 'draft',
  text: 'Hi Dana, thanks for the Q4 forecast; I will look at it today.',
  source: 'template',
  disclosure: ['Sends: the subject and who it is from.'],
  note: 'A skeleton from the thread.',
};

const STAGED = { ...DRAFT, text: '', disclosure: [], note: '', staged: true, cardId: 'card-42' };

const MANUAL_CARD: PluginCard = {
  id: 'headcount',
  title: 'Headcount',
  version: '0.1.0',
  pilot: false,
  state: 'enabled',
  freshness: 'fresh',
  cause: '',
  manualMetric: 'headcount',
  payload: { elements: [{ kind: 'metric', value: '10', label: 'Headcount' }] },
};

const SETUP_CARD: PluginCard = {
  id: 'excel-report',
  title: 'Workbook tracker',
  version: '0.1.0',
  pilot: false,
  state: 'enabled',
  freshness: 'setup',
  cause: '',
  payload: {
    elements: [],
    setup: { pluginId: 'excel-report', instanceId: 'main', name: 'Workbook tracker', step: 'source' },
  },
};

/** A promise whose answer one test hands over by hand. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** The shape api.ts reads: ok, status and a JSON body. */
function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body } as Response;
}

/** A fetch answer that never answers; the test resolves its gate. */
function heldFetch() {
  const gate = deferred<Response>();
  const fetchMock = vi.fn(() => gate.promise);
  vi.stubGlobal('fetch', fetchMock);
  return { gate, fetchMock };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('the research command bar and the answer region', () => {
  it('shows nothing under 100 ms, then the control and a shaped placeholder, and replaces it in place', async () => {
    vi.useFakeTimers();
    const { gate, fetchMock } = heldFetch();
    const onRefetch = vi.fn(async () => {});
    render(<Dashboard data={DATA} onRefetch={onRefetch} onExpired={NOOP} />);
    const field = screen.getByLabelText('Research question');
    fireEvent.change(field, { target: { value: 'What changed?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Research' }));
    const send = screen.getByRole('button', { name: 'Research' });
    // The guard is immediate; the visible busy state is not.
    expect(send).toBeDisabled();
    expect(send).not.toHaveAttribute('aria-busy');
    expect(screen.queryByRole('region', { name: 'Research answer' })).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(99);
    });
    expect(send).not.toHaveAttribute('aria-busy');
    expect(screen.queryByRole('region', { name: 'Research answer' })).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(send).toHaveAttribute('aria-busy', 'true');
    expect(send).toHaveAccessibleName('Asking your AI...');
    const section = screen.getByRole('region', { name: 'Research answer' });
    expect(section.querySelector('.brief-answer-copy')).not.toBeNull();
    expect(section.querySelector('.wire-lines')).not.toBeNull();
    expect(within(section).getByRole('status')).toHaveTextContent('Asking your AI for a sourced summary');
    // A second press during the wait starts nothing.
    fireEvent.click(send);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      gate.resolve(jsonResponse({
        status: 'ok',
        summary: 'Two reps named Meridian sold to them.',
        sources: ['crm'],
      }));
    });
    // The result replaced the placeholder inside the same landmark.
    expect(screen.getByRole('region', { name: 'Research answer' })).toBe(section);
    const answer = section.querySelector('.brief-answer-copy');
    expect(answer).toHaveTextContent('Two reps named Meridian sold to them.');
    expect(section.querySelector('.wire-lines')).toBeNull();
    expect(answer).toHaveAttribute('role', 'status');
    expect(onRefetch).toHaveBeenCalled();
  });

  it('says it is taking longer than usual after ten seconds, then names the failure in place and keeps the typed question', async () => {
    vi.useFakeTimers();
    const { gate } = heldFetch();
    render(<Dashboard data={DATA} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    const field = screen.getByLabelText('Research question');
    fireEvent.change(field, { target: { value: 'What changed?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Research' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('taking longer than usual');
    expect(status).toHaveTextContent('You may leave this page');

    await act(async () => {
      gate.resolve(jsonResponse({ status: 'degraded', cause: 'No AI key is saved.' }));
    });
    const section = screen.getByRole('region', { name: 'Research answer' });
    expect(within(section).getByRole('alert')).toHaveTextContent('No AI key is saved.');
    expect(field).toHaveValue('What changed?');
  });
});

describe('customize mode', () => {
  it('opens with its own pending control and a panel skeleton, not a pop-in', async () => {
    vi.useFakeTimers();
    const layoutGate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(() => layoutGate.promise));
    render(<Dashboard data={DATA} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Customize' }));
    const customize = screen.getByRole('button', { name: 'Customize' });
    expect(customize).toBeDisabled();
    expect(screen.queryByRole('region', { name: 'Customize dashboard' })).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(customize).toHaveAttribute('aria-busy', 'true');
    expect(customize).toHaveAccessibleName('Opening...');
    const panel = screen.getByRole('region', { name: 'Customize dashboard' });
    expect(panel).toHaveAttribute('aria-busy', 'true');
    expect(panel.querySelector('.cust-panel-wire')).not.toBeNull();
    expect(within(panel).getByRole('status')).toHaveTextContent('Reading your saved layout');

    await act(async () => {
      layoutGate.resolve(jsonResponse({ cards: LAYOUT }));
    });
    expect(screen.getByRole('button', { name: 'Done customizing' })).toBeInTheDocument();
    expect(screen.getByText(/Every change saves itself/)).toBeInTheDocument();
    expect(document.querySelector('.cust-panel-wire')).toBeNull();
  });

  it('holds every save control and shows the started one until the layout answers', async () => {
    const postGate = deferred<Response>();
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url) === '/api/layout' && init?.method === 'POST') return postGate.promise;
      if (String(url) === '/api/layout') return jsonResponse({ cards: LAYOUT });
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', fetchMock);
    const onRefetch = vi.fn(async () => {});
    render(<Dashboard data={DATA} onRefetch={onRefetch} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Customize' }));
    await screen.findByRole('button', { name: 'Done customizing' });
    fireEvent.click(screen.getByRole('button', { name: 'Hide Research' }));

    const hiding = await screen.findByRole('button', { name: 'Hiding Research...' });
    expect(hiding).toHaveAttribute('aria-busy', 'true');
    expect(hiding).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Hide Sales, last 24 hours' })).toBeDisabled();
    expect(screen.getByText('Hiding Research...')).toBeInTheDocument();

    await act(async () => {
      postGate.resolve(jsonResponse({ cards: LAYOUT.map((c) => (c.key === 'research' ? { ...c, hidden: true } : c)) }));
    });
    expect(await screen.findByText('Research hidden')).toBeInTheDocument();
    expect(onRefetch).toHaveBeenCalled();
  });

  it('reopens a renamed title with the typed words when the save fails', async () => {
    const postGate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url) === '/api/layout' && init?.method === 'POST') return postGate.promise;
      if (String(url) === '/api/layout') return jsonResponse({ cards: LAYOUT });
      return jsonResponse({});
    }));
    render(<Dashboard data={DATA} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Customize' }));
    await screen.findByRole('button', { name: 'Done customizing' });
    fireEvent.click(screen.getByRole('button', { name: 'Rename Research' }));
    const field = screen.getByLabelText('Title for Research');
    fireEvent.change(field, { target: { value: 'Digging' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save title' }));
    expect(await screen.findByRole('button', { name: 'Saving...' })).toHaveAttribute('aria-busy', 'true');

    await act(async () => {
      postGate.resolve(jsonResponse({}, 503));
    });
    expect(await screen.findByText(/layout was not saved/)).toBeInTheDocument();
    // The typed title is kept and the editor is open again.
    expect(screen.getByLabelText('Title for Research')).toHaveValue('Digging');
  });

  it('runs a skill on its own row and fills the answer card with the same shaped placeholder', async () => {
    const runGate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL) => {
      if (String(url) === '/api/layout') return jsonResponse({ cards: LAYOUT });
      if (String(url) === '/skills/1/run') return runGate.promise;
      return jsonResponse({});
    }));
    render(<Dashboard data={SKILL_DATA} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Customize' }));
    await screen.findByRole('button', { name: 'Done customizing' });
    fireEvent.click(screen.getByRole('button', { name: 'Run Monday numbers' }));
    const running = await screen.findByRole('button', { name: 'Running Monday numbers...' });
    expect(running).toHaveAttribute('aria-busy', 'true');
    expect(running).toBeDisabled();
    const answerCard = screen.getByRole('heading', { name: 'Research' }).closest('article') as HTMLElement;
    const placeholder = answerCard.querySelector('.answer-pending');
    expect(placeholder).not.toBeNull();
    expect(within(answerCard).getByRole('status')).toHaveTextContent('Running the saved ask');
    fireEvent.click(running);

    await act(async () => {
      runGate.resolve(jsonResponse({ status: 'ok', summary: 'Numbers done.' }));
    });
    expect(await within(answerCard).findByText('Numbers done.')).toBeInTheDocument();
    expect(answerCard.querySelector('.answer-pending')).toBeNull();
  });
});

describe('the Get started strip and the workbook walk', () => {
  it('names Opening on the picker and Connecting on the typed path', async () => {
    const pickGate = deferred<Response>();
    const connectGate = deferred<Response>();
    let pickCalls = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL) => {
      if (String(url).endsWith('/pick')) {
        pickCalls += 1;
        return pickGate.promise;
      }
      if (String(url) === '/sources/excel-watch') return connectGate.promise;
      return jsonResponse({});
    }));
    const data: DashboardData = {
      ...DATA,
      setup: {
        sample: false,
        sampleOffer: true,
        steps: [
          { id: 'ai', title: 'Add your AI key', reason: 'It answers.', href: '/settings#ai', action: null, done: true },
          { id: 'workbook', title: 'Open your sales workbook', reason: 'It holds the rows.', href: '/settings#tools', action: '/sources/excel-watch/pick', done: false },
          { id: 'calendar', title: 'Connect your calendar', reason: 'It holds the day.', href: '/walkthrough/calendar', action: null, done: false },
        ],
      },
    };
    render(<Dashboard data={data} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open' }));
    const opening = await screen.findByRole('button', { name: 'Opening...' });
    expect(opening).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Opening the file dialog');
    expect(pickCalls).toBe(1);

    await act(async () => {
      pickGate.resolve(jsonResponse({ path: null }));
    });
    expect(await screen.findByText(/The file dialog did not open/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Workbook path'), { target: { value: 'C:/desk/sales.xlsx' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    const connecting = await screen.findByRole('button', { name: 'Connecting...' });
    expect(connecting).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByText('Connecting the workbook')).toBeInTheDocument();
    await act(async () => {
      connectGate.resolve(jsonResponse({}));
    });
  });

  it('shows the sample switch working on itself', async () => {
    const gate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(() => gate.promise));
    const data: DashboardData = {
      ...DATA,
      setup: {
        sample: false,
        sampleOffer: true,
        steps: [
          { id: 'ai', title: 'Add your AI key', reason: 'It answers.', href: '/settings#ai', action: null, done: true },
          { id: 'workbook', title: 'Open your sales workbook', reason: 'It holds the rows.', href: '/settings#tools', action: null, done: true },
          { id: 'calendar', title: 'Connect your calendar', reason: 'It holds the day.', href: '/walkthrough/calendar', action: null, done: false },
        ],
      },
    };
    render(<Dashboard data={data} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Try it with sample data' }));
    const busy = await screen.findByRole('button', { name: 'Turning on the sample data...' });
    expect(busy).toHaveAttribute('aria-busy', 'true');
    expect(busy).toBeDisabled();
    expect(screen.getByText('Turning on the sample data')).toBeInTheDocument();
    await act(async () => {
      gate.resolve(jsonResponse({ key: 'sample_data', value: true }));
    });
  });
});

describe('a recommendation and a card menu', () => {
  it('dismisses on the button and says a failure in the row that owns it', async () => {
    const gate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(() => gate.promise));
    render(
      <Brief
        data={{ ...DATA, recommendations: [RECOMMENDATION] }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP}
      />,
    );
    const row = screen.getByText('Halvorsen Freight: December 15').closest('li') as HTMLElement;
    fireEvent.click(within(row).getByRole('button', { name: 'Not now' }));
    const dismissing = await within(row).findByRole('button', { name: 'Dismissing...' });
    expect(dismissing).toHaveAttribute('aria-busy', 'true');
    expect(dismissing).toBeDisabled();
    await act(async () => {
      gate.resolve(jsonResponse({}, 500));
    });
    const alert = await within(row).findByRole('alert');
    expect(alert).toHaveTextContent('Could not dismiss that decision. Try again.');
  });

  it('re-tests a plugin from the menu and says so in the card until the fresh payload lands', async () => {
    const gate = deferred<Response>();
    const onRefetch = vi.fn(async () => {});
    vi.stubGlobal('fetch', vi.fn(() => gate.promise));
    render(
      <PluginCardView
        card={{
          id: 'p1', title: 'Invoice tracker', version: '1.2.0', pilot: false,
          state: 'active', freshness: 'attention', cause: 'data source has not run',
        }}
        onRefetch={onRefetch}
        onExpired={NOOP}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^Widget options/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Re-test now' }));
    const line = (await screen.findByText('Re-testing the data source')).closest('p') as HTMLElement;
    expect(line).toHaveAttribute('role', 'status');
    const region = line.nextElementSibling as HTMLElement;
    expect(region).toHaveAttribute('aria-busy', 'true');
    expect(region).toHaveClass('region-busy');

    await act(async () => {
      gate.resolve(jsonResponse({}));
    });
    await waitFor(() => expect(onRefetch).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText('Re-testing the data source')).toBeNull());
  });

  it('re-tests the sales figure and the calendar reading in place', async () => {
    const salesGate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(() => salesGate.promise));
    render(
      <SalesCard
        sales={{ enabled: true, mode: 'live', status: HEALTHY_SALES }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^Widget options/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Re-test now' }));
    expect((await screen.findByText('Re-testing the workbook')).closest('[role="status"]')).not.toBeNull();
    await act(async () => {
      salesGate.resolve(jsonResponse({}));
    });
    cleanup();

    const calendarGate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(() => calendarGate.promise));
    render(
      <CommitmentsCard
        commitments={{ enabled: true, mode: 'live', status: COMMITMENTS_HEALTHY }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^Widget options/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Re-test now' }));
    expect((await screen.findByText('Re-testing the calendar')).closest('[role="status"]')).not.toBeNull();
    await act(async () => {
      calendarGate.resolve(jsonResponse({}));
    });
  });
});

describe('the sales connect walk', () => {
  it('names Opening for the dialog and Connecting for the typed path', async () => {
    const pickGate = deferred<Response>();
    const connectGate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL) => {
      if (String(url).endsWith('/pick')) return pickGate.promise;
      if (String(url) === '/sources/excel-watch') return connectGate.promise;
      return jsonResponse({});
    }));
    render(
      <SalesCard
        sales={{ enabled: true, mode: 'unconfigured', status: null }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Connect a workbook' }));
    const opening = await screen.findByRole('button', { name: 'Opening...' });
    expect(opening).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Opening the file dialog');
    await act(async () => {
      pickGate.resolve(jsonResponse({ path: null }));
    });
    expect(await screen.findByText(/The file dialog did not open/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Workbook path'), { target: { value: 'C:/desk/sales.xlsx' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    const connecting = await screen.findByRole('button', { name: 'Connecting...' });
    expect(connecting).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByText('Connecting the workbook')).toBeInTheDocument();
    await act(async () => {
      connectGate.resolve(jsonResponse({}));
    });
  });
});

describe('the press on a card', () => {
  it('drafts the reply with a draft-shaped placeholder, then stages it with its own verb', async () => {
    const draftGate = deferred<Response>();
    const stageGate = deferred<Response>();
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => draftGate.promise)
      .mockImplementationOnce(() => stageGate.promise);
    vi.stubGlobal('fetch', fetchMock);
    render(<PluginCardView card={DIGEST_CARD} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Draft the reply' }));
    const drafting = await screen.findByRole('button', { name: 'Drafting the reply...' });
    expect(drafting).toHaveAttribute('aria-busy', 'true');
    expect(drafting).toBeDisabled();
    await waitFor(() => expect(document.querySelector('.press-placeholder')).not.toBeNull());
    expect(screen.getByText('Drafting the reply')).toBeInTheDocument();

    await act(async () => {
      draftGate.resolve(jsonResponse(DRAFT));
    });
    expect(await screen.findByText(DRAFT.text)).toBeInTheDocument();
    expect(document.querySelector('.press-placeholder')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Stage as a reply card' }));
    const staging = await screen.findByRole('button', { name: 'Staging...' });
    expect(staging).toHaveAttribute('aria-busy', 'true');
    await act(async () => {
      stageGate.resolve(jsonResponse(STAGED));
    });
    expect(await screen.findByText('Staged as a card: card-42. Open the inbox to accept or edit it.'))
      .toHaveAttribute('role', 'status');
  });

  it('explains a range with its own verb and the answer replacing the placeholder', async () => {
    const gate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(() => gate.promise));
    render(<TrackerCard card={TRACKER_CARD} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Explain this range' }));
    const explaining = await screen.findByRole('button', { name: 'Explaining this range...' });
    expect(explaining).toHaveAttribute('aria-busy', 'true');
    await waitFor(() => expect(document.querySelector('.press-placeholder')).not.toBeNull());
    await act(async () => {
      gate.resolve(jsonResponse({ ...DRAFT, text: 'West booked nothing in weeks 8 and 9.' }));
    });
    expect(await screen.findByText('West booked nothing in weeks 8 and 9.')).toBeInTheDocument();
    expect(document.querySelector('.press-placeholder')).toBeNull();
  });
});

describe('the manual value form', () => {
  it('saves on its own pending label and keeps the typed value when the save fails', async () => {
    const gate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(() => gate.promise));
    render(<PluginCardView card={MANUAL_CARD} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.change(screen.getByLabelText('Set the value'), { target: { value: '42' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    const saving = await screen.findByRole('button', { name: 'Saving...' });
    expect(saving).toHaveAttribute('aria-busy', 'true');
    expect(saving).toBeDisabled();
    await act(async () => {
      gate.resolve(jsonResponse({ message: 'The value was not saved.' }, 400));
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('The value was not saved.');
    expect(screen.getByLabelText('Set the value')).toHaveValue(42);
  });
});

describe('the tracker setup sheet', () => {
  it('confirms with a pending label and the sheet keeps leaving possible', async () => {
    const confirmGate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);
      if (target.includes('/widgets/settings')) return jsonResponse({ suggest_headers_only: false });
      if (target.endsWith('/pick')) {
        return jsonResponse({
          preview: { sheet: 'Data', headers: ['Region', 'Booked'], rows: [['East', '10'], ['West', '5']] },
        });
      }
      if (target.endsWith('/suggest')) {
        return jsonResponse({
          proposal: {
            labelColumn: 'Region', valueColumn: 'Booked', aggregate: 'sum',
            rows: [0, 1], reason: 'Booked looks like the amount.', source: 'heuristic',
          },
        });
      }
      if (target.endsWith('/confirm') && init?.method === 'POST') return confirmGate.promise;
      return jsonResponse({});
    }));
    render(<TrackerCard card={SETUP_CARD} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Set up' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Open a workbook' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Accept' }));
    const confirm = await screen.findByRole('button', { name: 'Confirm' });
    fireEvent.click(confirm);
    const saving = await screen.findByRole('button', { name: 'Saving...' });
    expect(saving).toHaveAttribute('aria-busy', 'true');
    expect(saving).toBeDisabled();
    // Leaving is still possible while the request runs.
    expect(screen.getByRole('button', { name: 'Close dialog' })).toBeEnabled();
    await act(async () => {
      confirmGate.resolve(jsonResponse({ step: 'done' }));
    });
  });
});

describe('a sheet closed while its request runs', () => {
  it('announces the outcome on the page the reader returned to', async () => {
    const confirmGate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);
      if (target.endsWith('/pick')) {
        return jsonResponse({
          preview: { sheet: 'Data', headers: ['Region', 'Booked'], rows: [['East', '10']] },
        });
      }
      if (target.endsWith('/suggest')) return jsonResponse({ proposal: null });
      if (target.endsWith('/confirm') && init?.method === 'POST') return confirmGate.promise;
      return jsonResponse({});
    }));
    const data: DashboardData = {
      ...DATA,
      layout: { cards: [{ key: 'excel-report', title: null }] },
      plugins: { cards: [SETUP_CARD] },
    };
    render(<Dashboard data={data} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Set up' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Open a workbook' }));
    // No suggestion offered: assign the columns and continue.
    fireEvent.click(await screen.findByRole('button', { name: 'Booked' }));
    fireEvent.click(screen.getByRole('radio', { name: 'Row label' }));
    fireEvent.click(screen.getByRole('button', { name: 'Region' }));
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm' }));
    await screen.findByRole('button', { name: 'Saving...' });
    // The reader leaves while the sheet is still busy.
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    await act(async () => {
      confirmGate.resolve(jsonResponse({ step: 'done' }));
    });
    expect(screen.getByText('The tracker was saved. It is on the desk now.')).toBeInTheDocument();
  });
});

describe('the first load and the poll', () => {  it('draws the bento skeleton after 100 ms and the ten-second line after ten seconds', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})));
    render(<App />);
    expect(document.getElementById('dashboard-main')).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(99);
    });
    expect(document.getElementById('dashboard-main')).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    const main = document.getElementById('dashboard-main') as HTMLElement;
    expect(main).toHaveAttribute('aria-busy', 'true');
    expect(main.querySelector('.brief')).not.toBeNull();
    expect(main.querySelector('.cell-hero')).not.toBeNull();
    expect(document.querySelector('.center-card')).toBeNull();
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Reading the dashboard…');
    expect(status).toHaveAttribute('aria-busy', 'true');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(screen.getByRole('status')).toHaveTextContent('taking longer than usual');
  });

  it('keeps the last reading and adds one quiet line when a poll fails, then clears it', async () => {
    vi.useFakeTimers();
    let reads = 0;
    let fail = true;
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL) => {
      if (String(url) !== '/api/dashboard') return jsonResponse({});
      reads += 1;
      if (reads === 1) return jsonResponse(DATA);
      if (fail) throw new TypeError('Failed to fetch');
      return jsonResponse(DATA);
    }));
    render(<App />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(document.getElementById('dashboard-main')).not.toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
    expect(screen.getByText(/The desk could not be reached just now/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'The dashboard did not load' })).toBeNull();
    fail = false;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
    expect(screen.queryByText(/The desk could not be reached just now/)).toBeNull();
  });
});
