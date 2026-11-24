// R24 (spec 022): with an open step the Get started strip renders above
// the tiles and each open step is one click; with every step done it does
// not render. The steps are the server's setup object, read as sent: the
// strip never decides on its own that a source is connected.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Dashboard from '../dashboard/Dashboard';
import type { DashboardData, SetupData, SetupStep } from '../types';

const NOOP_REFETCH = async () => {};
const NOOP_EXPIRED = () => {};
const STRIP_NAME = 'Three steps and your desk is ready';
const DISMISSED_KEY = 'agentdesk.setupDismissed';

const STEPS: SetupStep[] = [
  {
    id: 'ai', title: 'Add your AI key',
    reason: 'The assistant, your calendar breakdowns and memory all use it.',
    href: '/settings#ai', action: null, done: false,
  },
  {
    id: 'workbook', title: 'Open your sales workbook',
    reason: 'Your pipeline figure and the moves come from it.',
    href: '/settings#tools', action: '/sources/excel-watch/pick', done: false,
  },
  {
    id: 'calendar', title: 'Connect your calendar',
    reason: 'Today’s commitment and your digest come from it.',
    href: '/walkthrough/calendar', action: null, done: false,
  },
];

/** The setup object with the given steps marked done. */
function setupData(done: boolean[], sample = false,
                   sampleOffer = !done[1] && !done[2]): SetupData {
  return { sample, sampleOffer, steps: STEPS.map((step, index) => ({ ...step, done: done[index] })) };
}

const BASE: DashboardData = {
  version: '0.0.0-test',
  flags: { excelEnabled: true, calendarEnabled: true, endpointEnabled: true },
  sources: { connected: 0, total: 3, items: [] },
  sales: { enabled: true, mode: 'unconfigured', status: null },
  commitments: { enabled: true, mode: 'unavailable', status: null },
  research: { enabled: true, lastAnsweredTs: null },
  inbox: { waiting: 0 },
  skills: [],
  layout: { cards: [] },
  plugins: { cards: [] },
};

/** The desk with the given setup object; an AI source row when asked for. */
function desk(setup: SetupData, aiSaved = false): DashboardData {
  const items = aiSaved
    ? [{ id: 'research-endpoint', status: 'connected', detail: 'AI connected.' }]
    : [];
  return { ...BASE, setup, sources: { ...BASE.sources, connected: aiSaved ? 1 : 0, items } };
}

/** Stub the two workbook calls: the picker's answer and a quiet connect. */
function stubWorkbook(path: string | null) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/pick')) return Response.json({ path });
    if (url === '/sources/excel-watch') {
      expect(JSON.parse(String(init?.body))).toEqual({ path });
      return Response.json({});
    }
    return Response.json({ key: 'sample_data', value: true });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe('the Get started strip (R24)', () => {
  it('renders above the tiles with the three steps in order, none done', () => {
    render(<Dashboard data={desk(setupData([false, false, false]))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    const strip = screen.getByRole('region', { name: STRIP_NAME });
    expect(strip).toHaveTextContent('0 of 3 done');
    // The steps come in the server's order, the first open one current.
    const rows = within(strip).getAllByRole('listitem');
    expect(rows.map((row) => row.querySelector('.gs-title')?.textContent)).toEqual(STEPS.map((step) => step.title));
    expect(rows[0]).toHaveAttribute('aria-current', 'step');
    expect(rows[1]).not.toHaveAttribute('aria-current');
    // Above the tiles: the pipeline cell follows the strip in the document.
    const hero = document.querySelector('.cell-hero');
    expect(hero).not.toBeNull();
    expect(strip.compareDocumentPosition(hero as Element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The Decisions cell does not repeat what the strip already asks.
    const decisions = screen.getByRole('region', { name: 'Needs a decision' });
    expect(within(decisions).queryByText('Add your AI key')).toBeNull();
    expect(within(decisions).queryByText('Ask your first question')).toBeNull();
  });

  it('makes each open step one click', () => {
    render(<Dashboard data={desk(setupData([false, false, false]))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    const strip = screen.getByRole('region', { name: STRIP_NAME });
    expect(within(strip).getByRole('link', { name: 'Add' })).toHaveAttribute('href', '/settings#ai');
    expect(within(strip).getByRole('button', { name: 'Open' })).toBeInTheDocument();
    expect(within(strip).getByRole('link', { name: 'Connect' })).toHaveAttribute('href', '/walkthrough/calendar');
    // The strip holds no primary: the question bar keeps the one solid action.
    expect(strip.querySelector('.btn-primary')).toBeNull();
  });

  it('marks a done step and moves the current mark to the next open one', () => {
    render(<Dashboard data={desk(setupData([true, false, false]))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    const strip = screen.getByRole('region', { name: STRIP_NAME });
    expect(strip).toHaveTextContent('1 of 3 done');
    const rows = within(strip).getAllByRole('listitem');
    expect(rows[0]).toHaveClass('is-done');
    expect(rows[0]).toHaveTextContent('Done');
    expect(within(rows[0]).queryByRole('link', { name: 'Add' })).toBeNull();
    expect(rows[1]).toHaveAttribute('aria-current', 'step');
  });

  it('opens the workbook picker from its step and connects what comes back', async () => {
    const path = 'C:\\books\\sales.xlsx';
    const fetchMock = stubWorkbook(path);
    const onRefetch = vi.fn(NOOP_REFETCH);
    const user = userEvent.setup();
    render(<Dashboard data={desk(setupData([false, false, false]))} onRefetch={onRefetch} onExpired={NOOP_EXPIRED} />);
    const strip = screen.getByRole('region', { name: STRIP_NAME });
    await user.click(within(strip).getByRole('button', { name: 'Open' }));
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      '/sources/excel-watch/pick', '/sources/excel-watch',
    ]);
    expect(onRefetch).toHaveBeenCalled();
  });

  it('falls back to the typed path when the file dialog does not open', async () => {
    stubWorkbook(null);
    const user = userEvent.setup();
    render(<Dashboard data={desk(setupData([false, false, false]))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    const strip = screen.getByRole('region', { name: STRIP_NAME });
    await user.click(within(strip).getByRole('button', { name: 'Open' }));
    expect(await within(strip).findByText('The file dialog did not open. Type the workbook path below and press Connect.'))
      .toBeInTheDocument();
    expect(within(strip).getByLabelText('Workbook path')).toBeInTheDocument();
  });

  it('offers sample data while nothing is connected, and a way to hide it while it is in use', async () => {
    const user = userEvent.setup();
    const first = stubWorkbook(null);
    const onRefetch = vi.fn(NOOP_REFETCH);
    render(<Dashboard data={desk(setupData([false, false, false]))} onRefetch={onRefetch} onExpired={NOOP_EXPIRED} />);
    expect(screen.queryByRole('button', { name: 'Hide sample data' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Try it with sample data' }));
    expect(first.mock.calls[0][0]).toBe('/settings/toggle');
    expect(JSON.parse(String(first.mock.calls[0][1]?.body))).toEqual({ key: 'sample_data' });
    expect(onRefetch).toHaveBeenCalledTimes(1);

    // The switch answered and the desk now reports the sample set in use.
    cleanup();
    const second = stubWorkbook(null);
    render(<Dashboard data={desk(setupData([false, false, false], true))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    expect(screen.getByText('You are looking at sample data.'));
    expect(screen.queryByRole('button', { name: 'Try it with sample data' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Hide sample data' }));
    expect(second.mock.calls[0][0]).toBe('/settings/toggle');

    // The offer waits for a real source, not for the AI step: with the
    // key saved and no workbook or calendar it still shows.
    cleanup();
    render(<Dashboard data={desk(setupData([true, false, false]))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    expect(screen.getByRole('button', { name: 'Try it with sample data' })).toBeInTheDocument();

    // A real workbook or calendar is what withdraws it.
    cleanup();
    render(<Dashboard data={desk(setupData([false, true, false]))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    expect(screen.queryByRole('button', { name: 'Try it with sample data' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Hide sample data' })).toBeNull();
  });

  it('says so when the sample switch does not answer', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ error: 'settings are not available' }, { status: 503 })));
    const user = userEvent.setup();
    render(<Dashboard data={desk(setupData([false, false, false]))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    await user.click(screen.getByRole('button', { name: 'Try it with sample data' }));
    expect(await screen.findByText('Sample data did not turn on. Try again.')).toBeInTheDocument();
  });

  it('hides on Not now for this sitting, and the header brings it back with focus', async () => {
    const user = userEvent.setup();
    render(<Dashboard data={desk(setupData([false, false, false]))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    await user.click(screen.getByRole('button', { name: 'Not now' }));
    expect(screen.queryByRole('region', { name: STRIP_NAME })).toBeNull();
    expect(sessionStorage.getItem(DISMISSED_KEY)).toBe('1');
    // The header says how much is left instead of showing the strip.
    await user.click(screen.getByRole('button', { name: 'Finish setup, 3 steps left' }));
    const strip = await screen.findByRole('region', { name: STRIP_NAME });
    await waitFor(() => expect(strip).toHaveFocus());
    expect(sessionStorage.getItem(DISMISSED_KEY)).toBeNull();
    expect(screen.queryByRole('button', { name: /Finish setup/ })).toBeNull();
  });

  it('remembers the dismissal for this sitting', () => {
    sessionStorage.setItem(DISMISSED_KEY, '1');
    render(<Dashboard data={desk(setupData([false, true, false]))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    expect(screen.queryByRole('region', { name: STRIP_NAME })).toBeNull();
    expect(screen.getByRole('button', { name: 'Finish setup, 2 steps left' })).toBeInTheDocument();
  });

  it('does not render once every step is done', () => {
    render(<Dashboard data={desk(setupData([true, true, true]), true)} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    expect(screen.queryByRole('region', { name: STRIP_NAME })).toBeNull();
    expect(screen.queryByRole('button', { name: /Finish setup/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /sample data/ })).toBeNull();
  });

  it('leaves the header to Customize: the plugin wizard moved to the Plugins page', () => {
    render(<Dashboard data={desk(setupData([false, false, false]))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    expect(screen.queryByRole('button', { name: 'Add plugin' })).toBeNull();
    expect(document.querySelector('form[action="/wizard/start"]')).toBeNull();
    expect(screen.getByRole('button', { name: 'Customize' })).toBeInTheDocument();
  });
});

describe('the question bar without an AI (spec 022)', () => {
  it('offers Connect your AI and sends nothing', () => {
    const fetchMock = stubWorkbook(null);
    render(<Dashboard data={desk(setupData([false, false, false]))} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    expect(screen.getByRole('link', { name: 'Connect your AI' })).toHaveAttribute('href', '/settings#ai');
    expect(screen.getByText('Add your AI key to ask.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Research' })).toBeNull();
    const field = screen.getByRole('textbox', { name: 'Research question' });
    fireEvent.change(field, { target: { value: 'What moved today?' } });
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(fetchMock).not.toHaveBeenCalled();
    // The question is kept, not thrown away.
    expect(field).toHaveValue('What moved today?');
  });

  it('goes back to asking once a key is saved', () => {
    render(<Dashboard data={desk(setupData([true, false, false]), true)} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    expect(screen.queryByRole('link', { name: 'Connect your AI' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Research' })).toBeInTheDocument();
  });
});
