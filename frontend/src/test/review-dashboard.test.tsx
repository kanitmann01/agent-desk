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
