// The dashboard review's own regressions: the 100 ms gate on a layout save,
// the exact stage value behind its compact label, a failure that is not an
// empty answer, the ten-second line on the two slow-disk saves, and the
// Page watch offer on a desk that cannot read the web.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Dashboard from '../dashboard/Dashboard';
import Brief from '../dashboard/Brief';
import PluginCardView from '../dashboard/PluginCardView';
import { StageChart } from '../dashboard/cells';
import type { DashboardData, LayoutCardState, PluginCard } from '../types';

const NOOP = () => {};
const NOOP_REFETCH = async () => {};

const LAYOUT: LayoutCardState[] = [
  { key: 'sales', hidden: false, title: null },
  { key: 'commitments', hidden: false, title: null },
  { key: 'research', hidden: false, title: null },
  { key: 'skills', hidden: false, title: null },
];

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
      { key: 'skills', title: null },
    ],
  },
  plugins: { cards: [] },
};

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

/** A promise whose answer one test hands over by hand. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

/** The shape api.ts reads: ok, status and a JSON body. */
function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body } as Response;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('the layout save shows its wait only after 100 ms', () => {
  it('is inert at 30 ms and shows the pending verb at 100 ms', async () => {
    vi.useFakeTimers();
    const postGate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url) === '/api/layout' && init?.method === 'POST') return postGate.promise;
      if (String(url) === '/api/layout') return jsonResponse({ cards: LAYOUT });
      return jsonResponse({});
    }));
    render(<Dashboard data={DATA} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Customize' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Hide Research' }));

    // The guard is immediate; the pending verb is not.
    const inert = screen.getByRole('button', { name: 'Hide Research' });
    expect(inert).toBeDisabled();
    expect(inert).not.toHaveAttribute('aria-busy');
    expect(screen.queryByText('Hiding Research...')).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30);
    });
    expect(screen.getByRole('button', { name: 'Hide Research' })).toBeDisabled();
    expect(screen.queryByText('Hiding Research...')).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(70);
    });
    const busy = screen.getByRole('button', { name: 'Hiding Research...' });
    expect(busy).toHaveAttribute('aria-busy', 'true');
    expect(busy).toBeDisabled();
    expect(screen.getByText('Hiding Research...')).toBeInTheDocument();

    await act(async () => {
      postGate.resolve(jsonResponse({ cards: LAYOUT.map((c) => (c.key === 'research' ? { ...c, hidden: true } : c)) }));
    });
  });
});

describe('a stage label carries its exact value', () => {
  it('titles the compact label with the stage and the full signed value', () => {
    render(<StageChart stages={[{ stage: 'Prospect', net: 1234567, deals: 3 }]} />);
    const value = document.querySelector('.stage-val') as HTMLElement;
    expect(value).not.toBeNull();
    expect(value).toHaveTextContent('1.2M');
    expect(value).toHaveAttribute('title', 'Prospect: +1,234,567');
  });
});

describe('a refused research answer', () => {
  it('shows the server error instead of an empty answer', async () => {
    const onRefetch = vi.fn(async () => {});
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(
      { error: 'The AI answered without a summary.' },
      500,
    )));
    render(<Dashboard data={DATA} onRefetch={onRefetch} onExpired={NOOP} />);
    fireEvent.change(screen.getByLabelText('Research question'), { target: { value: 'What changed?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Research' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The AI answered without a summary.');
    // The failure is said in place; no blank answer claims to be one.
    expect(document.querySelector('.brief-answer-copy')).toBeNull();
    expect(onRefetch).not.toHaveBeenCalled();
  });
});

describe('the ten-second line on the slow-disk saves', () => {
  it('says a customize save is taking longer after ten seconds', async () => {
    vi.useFakeTimers();
    const postGate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url) === '/api/layout' && init?.method === 'POST') return postGate.promise;
      if (String(url) === '/api/layout') return jsonResponse({ cards: LAYOUT });
      return jsonResponse({});
    }));
    render(<Dashboard data={DATA} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.click(screen.getByRole('button', { name: 'Customize' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Hide Research' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    const status = screen.getByText(/Hiding Research/).closest('[role="status"]') as HTMLElement;
    expect(status).toHaveTextContent('taking longer than usual');
    expect(status).toHaveTextContent('You may leave this page');
    await act(async () => {
      postGate.resolve(jsonResponse({ cards: LAYOUT.map((c) => (c.key === 'research' ? { ...c, hidden: true } : c)) }));
    });
  });

  it('says a manual value save is taking longer after ten seconds', async () => {
    vi.useFakeTimers();
    const gate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(() => gate.promise));
    render(<PluginCardView card={MANUAL_CARD} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.change(screen.getByLabelText('Set the value'), { target: { value: '42' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    const status = screen.getByText(/Saving the value/).closest('[role="status"]') as HTMLElement;
    expect(status).toHaveTextContent('taking longer than usual');
    expect(status).toHaveTextContent('You may leave this page');
    await act(async () => {
      gate.resolve(jsonResponse({}));
    });
  });
});

describe('the research answer card follows the layout', () => {
  it('shows the layout\'s custom title on the answer region', async () => {
    const data: DashboardData = {
      ...DATA,
      layout: {
        cards: DATA.layout.cards.map((card) => (
          card.key === 'research' ? { ...card, title: 'Digging' } : card
        )),
      },
    };
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ status: 'ok', summary: 'An answer.', sources: [] })));
    render(<Dashboard data={data} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.change(screen.getByLabelText('Research question'), { target: { value: 'What changed?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Research' }));
    const region = await screen.findByRole('region', { name: 'Research answer' });
    expect(within(region).getByRole('heading', { name: 'Digging' })).toBeInTheDocument();
  });

  it('renders no answer region when the layout hides the research card', async () => {
    const gate = deferred<Response>();
    const data: DashboardData = {
      ...DATA,
      layout: { cards: DATA.layout.cards.filter((card) => card.key !== 'research') },
    };
    vi.stubGlobal('fetch', vi.fn(() => gate.promise));
    render(<Dashboard data={data} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    fireEvent.change(screen.getByLabelText('Research question'), { target: { value: 'What changed?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Research' }));
    await act(async () => {
      gate.resolve(jsonResponse({ status: 'ok', summary: 'An answer.', sources: [] }));
    });
    expect(screen.queryByRole('region', { name: 'Research answer' })).toBeNull();
    // The command bar is always present, even when its card is hidden.
    expect(screen.getByLabelText('Research question')).toBeInTheDocument();
  });
});

describe('a plugin that cannot run on this desk', () => {
  const CANNOT_RUN: PluginCard = {
    id: 'competitor-watch',
    title: 'Competitor Watch',
    version: '0.1.0',
    pilot: true,
    state: 'enabled',
    freshness: 'attention',
    cause: 'This desk cannot read web pages yet.',
    checkedAt: '2026-11-24T18:42:33',
    pluginId: 'competitor-watch',
    instanceId: 'main',
    payload: { elements: [], source: { reason: 'no-transport' } },
  };

  const SETUP_WATCH: PluginCard = {
    id: 'competitor-watch~custom',
    title: 'Competitor Watch setup',
    version: '0.1.0',
    pilot: false,
    state: 'enabled',
    freshness: 'attention',
    cause: '',
    payload: {
      elements: [],
      setup: { pluginId: 'competitor-watch', instanceId: 'custom', name: 'Competitor Watch setup', step: 'source' },
    },
  };

  const FRESH_WATCH: PluginCard = {
    ...CANNOT_RUN,
    id: 'competitor-watch~live',
    title: 'Competitor Watch live',
    freshness: 'fresh',
    cause: '',
    payload: { elements: [{ kind: 'text', label: 'Reading', text: 'A change was seen.' }] },
  };

  const FRESH_PLUGIN: PluginCard = {
    id: 'notes',
    title: 'Notes digester',
    version: '1.0.0',
    pilot: false,
    state: 'enabled',
    freshness: 'fresh',
    cause: '',
    payload: { elements: [{ kind: 'text', label: 'Reading', text: 'A note.' }] },
  };

  // The tracker's amber card: the workbook moved, locked or is unreadable.
  // It carries no payload and no setup step, and only its own Set up control
  // can fix it.
  const TRACKER_ATTENTION: PluginCard = {
    id: 'excel-report~moved',
    title: 'Pipeline tracker',
    version: '0.1.0',
    pilot: false,
    state: 'enabled',
    freshness: 'attention',
    cause: 'The workbook moved or is unreadable.',
    pluginId: 'excel-report',
    instanceId: 'moved',
    payload: null,
  };

  // A non-tracker attention card with no payload for a reason other than
  // the transport: nothing says it cannot run here, so it must fail open.
  const NULL_PAYLOAD: PluginCard = {
    id: 'headcount-digest',
    title: 'Headcount digest',
    version: '0.1.0',
    pilot: false,
    state: 'enabled',
    freshness: 'attention',
    cause: 'The data source did not answer.',
    payload: null,
  };

  /** The home screen with one plugin card set and no builtin columns. */
  function show(deskNetwork: boolean | undefined, cards: PluginCard[]) {
    const data: DashboardData = {
      ...DATA,
      ...(deskNetwork === undefined ? {} : { deskNetwork }),
      layout: { cards: cards.map((card) => ({ key: card.id, title: null })) },
      plugins: { cards },
    };
    render(<Brief data={data} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
  }

  it('shows the Page watch placeholder instead of a tile that cannot run', () => {
    show(false, [CANNOT_RUN]);
    expect(screen.queryByText('Competitor Watch')).toBeNull();
    expect(screen.queryByText('Re-test available')).toBeNull();
    expect(
      screen.getByText('No page is being watched. Name one page and see what changed on it.'),
    ).toBeInTheDocument();
    expect(screen.getByText('This desk cannot read web pages yet')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Add a page' })).toBeNull();
  });

  it('explains the absence on an older payload with no deskNetwork', () => {
    show(undefined, [CANNOT_RUN, FRESH_PLUGIN]);
    expect(screen.queryByText('Competitor Watch')).toBeNull();
    expect(
      screen.getByText('No page is being watched. Name one page and see what changed on it.'),
    ).toBeInTheDocument();
    expect(screen.getByText('This desk cannot read web pages yet')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Add a page' })).toBeNull();
    const health = document.querySelector('.cell-health') as HTMLElement;
    expect(within(health).queryByText('Competitor Watch')).toBeNull();
    expect(within(health).getByText('Notes digester')).toBeInTheDocument();
  });

  it('carries the line under the sample watch when the desk cannot read the web', () => {
    const data: DashboardData = {
      ...DATA,
      sample: true,
      deskNetwork: false,
      layout: { cards: [{ key: CANNOT_RUN.id, title: null }] },
      plugins: { cards: [CANNOT_RUN] },
    };
    render(<Brief data={data} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
    const watch = document.querySelector('.cell-watch') as HTMLElement;
    expect(within(watch).getByText('SAMPLE DATA')).toBeInTheDocument();
    expect(within(watch).getByText('This desk cannot read web pages yet')).toBeInTheDocument();
    expect(screen.queryByText('Competitor Watch')).toBeNull();
  });

  it('keeps a tracker whose workbook moved, with its Set up control', () => {
    show(false, [TRACKER_ATTENTION]);
    expect(screen.getAllByText('Pipeline tracker').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Set up' })).toBeInTheDocument();
    const health = document.querySelector('.cell-health') as HTMLElement;
    expect(within(health).getByText('Pipeline tracker')).toBeInTheDocument();
    expect(within(health).getByText('0 of 1 live')).toBeInTheDocument();
  });

  it('keeps a null-payload attention card with no transport reason', () => {
    show(false, [NULL_PAYLOAD]);
    expect(screen.getAllByText('Headcount digest').length).toBeGreaterThan(0);
    expect(screen.getByText('Re-test available')).toBeInTheDocument();
    const health = document.querySelector('.cell-health') as HTMLElement;
    expect(within(health).getByText('Headcount digest')).toBeInTheDocument();
    expect(within(health).getByText('0 of 1 live')).toBeInTheDocument();
  });

  it('never hides an attention card that carries a setup step', () => {
    show(false, [SETUP_WATCH]);
    expect(
      screen.getByRole('heading', { level: 3, name: 'Competitor Watch setup' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Set up' })).toBeInTheDocument();
    expect(
      screen.queryByText('No page is being watched. Name one page and see what changed on it.'),
    ).toBeNull();
  });

  it('does not show the placeholder next to a live watch card', () => {
    show(false, [FRESH_WATCH]);
    expect(screen.getAllByText('Competitor Watch live').length).toBeGreaterThan(0);
    expect(
      screen.queryByText('No page is being watched. Name one page and see what changed on it.'),
    ).toBeNull();
  });

  it('keeps the cannot-run plugin out of Desk health', () => {
    show(false, [CANNOT_RUN, FRESH_PLUGIN]);
    const health = document.querySelector('.cell-health') as HTMLElement;
    expect(within(health).getByText('Notes digester')).toBeInTheDocument();
    expect(within(health).queryByText('Competitor Watch')).toBeNull();
    expect(within(health).getByText('1 of 1 live')).toBeInTheDocument();
  });
});

describe('the Page watch offer on a desk without the network', () => {
  function show(deskNetwork: boolean | undefined) {
    const data: DashboardData = {
      ...DATA,
      ...(deskNetwork === undefined ? {} : { deskNetwork }),
    };
    render(<Brief data={data} onRefetch={NOOP_REFETCH} onExpired={NOOP} />);
  }

  it('offers no dead link when the desk cannot read web pages', () => {
    show(false);
    expect(screen.queryByRole('link', { name: 'Add a page' })).toBeNull();
    expect(screen.getByText('This desk cannot read web pages yet')).toBeInTheDocument();
  });

  it('keeps the offer when the desk can read web pages', () => {
    show(true);
    expect(screen.getByRole('link', { name: 'Add a page' })).toHaveAttribute(
      'href',
      '/marketplace/plugin/competitor-watch',
    );
    expect(screen.queryByText('This desk cannot read web pages yet')).toBeNull();
  });

  it('keeps today\'s behaviour when the field is absent', () => {
    show(undefined);
    expect(screen.getByRole('link', { name: 'Add a page' })).toBeInTheDocument();
    expect(screen.queryByText('This desk cannot read web pages yet')).toBeNull();
  });
});
