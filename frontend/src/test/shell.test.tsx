// The shell ticket's behavior suite: the rail, the hero band, the
// research command bar and the centered app states, on the warm-paper
// system. Rendering-level checks: the effects wrappers are gone, the
// honest copy and the keyboard behaviors stay.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import CommandBar from '../components/CommandBar';
import Dashboard from '../dashboard/Dashboard';
import Rail from '../dashboard/Rail';
import { dateLineFor, greetingFor } from '../fmt';
import type { DashboardData, SetupData } from '../types';

const DATA: DashboardData = {
  version: '0.0.0-test',
  flags: { excelEnabled: false, calendarEnabled: false, endpointEnabled: false },
  sources: { connected: 1, total: 3, items: [] },
  sales: { enabled: true, mode: 'unconfigured', status: null },
  commitments: { enabled: true, mode: 'unavailable', status: null },
  research: { enabled: true, lastAnsweredTs: null },
  inbox: { waiting: 2 },
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

/** A fresh desk's setup object, as the server reports it (spec 022). */
const COLD_SETUP: SetupData = {
  sample: false,
  sampleOffer: true,
  steps: [
    { id: 'ai', title: 'Add your AI key', reason: 'The assistant uses it.', href: '/settings#ai', action: null, done: false },
    { id: 'workbook', title: 'Open your sales workbook', reason: 'Your pipeline figure comes from it.', href: '/settings#tools', action: '/sources/excel-watch/pick', done: false },
    { id: 'calendar', title: 'Connect your calendar', reason: 'Your digest comes from it.', href: '/walkthrough/calendar', action: null, done: false },
  ],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  // The rail collapse persists by design; tests start from a neutral rail.
  localStorage.removeItem('agentdesk.railCollapsed');
});

// The hero tests pin the clock so a minute rollover between render and
// assertion cannot flake the greeting or the date line.
const NOON = new Date(2026, 10, 12, 12, 0, 0);
function pinClock() {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOON);
}

describe('the rail', () => {
  it('renders the brand as plain text and the eight daily entries', () => {
    render(<Rail inboxWaiting={2} />);
    // The brand carries no gradient: a plain span in the ink.
    const brand = document.querySelector<HTMLElement>('.brand-name');
    expect(brand).toHaveTextContent('Agent Desk');
    expect(brand?.style.backgroundImage).toBe('');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(nav).toHaveTextContent('Dashboard');
    expect(nav).toHaveTextContent('Inbox');
    expect(nav).toHaveTextContent('Assistant');
    expect(nav).toHaveTextContent('Agents');
    expect(nav).toHaveTextContent('Settings');
    // The marketplace is the Plugins page (spec 022): one SPA surface
    // with a deep-linkable route, not a server page.
    expect(screen.getByRole('link', { name: 'Plugins' })).toHaveAttribute(
      'href',
      '/marketplace',
    );
    // Activity, Capabilities and Peers moved under Settings: the rail
    // carries the surfaces a person uses every day, not every URL.
    for (const retired of ['Activity', 'Capabilities', 'Peers']) {
      expect(screen.queryByText(retired)).toBeNull();
    }
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('shows no inbox count when nothing waits', () => {
    render(<Rail inboxWaiting={0} />);
    expect(document.querySelector('.rail .count')).toBeNull();
  });

  it('keeps every entry label in its own span and names the avatar', () => {
    render(<Rail inboxWaiting={2} />);
    expect(document.querySelectorAll('.rail-label')).toHaveLength(8);
    // The avatar is a 30px square: its initials can be elided, so the
    // same name the user line carries is the reachable title.
    expect(document.querySelector('.rail .user .avatar'))
      .toHaveAttribute('title', 'Agent Desk');
  });

  it('keeps Memory and Mail on the rail', () => {
    render(<Rail inboxWaiting={0} />);
    const nav = screen.getByRole('navigation', { name: 'Main' });
    for (const [name, href] of [
      ['Memory', '/memory'],
      ['Mail', '/mail'],
    ] as Array<[string, string]>) {
      const link = screen.getByRole('link', { name });
      expect(link).toHaveAttribute('href', href);
      expect(nav).toContainElement(link);
    }
  });

  it('carries Agents beside Assistant as a server page', () => {
    render(<Rail inboxWaiting={0} />);
    const nav = screen.getByRole('navigation', { name: 'Main' });
    const link = screen.getByRole('link', { name: 'Agents' });
    expect(link).toHaveAttribute('href', '/agents');
    expect(nav).toContainElement(link);
    // The entry sits directly after its neighbour Assistant, keeps the
    // single-letter mark the collapsed rail shows, and like Assistant
    // is a server page: the SPA never marks it current.
    const assistant = screen.getByRole('link', { name: 'Assistant' });
    expect(link.previousElementSibling).toBe(assistant);
    expect(link.querySelector('.rail-mark')).toHaveTextContent('A');
    expect(link).not.toHaveAttribute('aria-current');
  });

  it('carries a collapse control that announces its state', () => {
    render(<Rail inboxWaiting={0} />);
    // The rail starts expanded, and the button expands the nav, so the
    // initial state is expanded.
    const toggle = screen.getByRole('button', { name: 'Collapse navigation' });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });

  it('collapses on click, keeps named links and the count, and persists', async () => {
    const user = userEvent.setup();
    render(
      <div className="app">
        <Rail inboxWaiting={4} />
      </div>,
    );
    const toggle = screen.getByRole('button', { name: 'Collapse navigation' });
    await user.click(toggle);
    const app = document.querySelector('.app') as HTMLElement;
    expect(app).toHaveClass('rail-collapsed');
    // The button expands the nav: a collapsed rail announces collapsed.
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveAttribute('aria-label', 'Expand navigation');
    // The visible labels hide when collapsed, so each link carries its
    // own accessible name; the Inbox link names its waiting count.
    expect(screen.getByRole('link', { name: 'Inbox, 4 waiting' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings' })).toBeInTheDocument();
    // The inbox count stays visible while the labels hide: it is the
    // one signal worth keeping on a collapsed rail.
    expect(document.querySelector('.rail .count')).not.toBeNull();
    expect(localStorage.getItem('agentdesk.railCollapsed')).toBe('1');

    await user.click(toggle);
    expect(app).not.toHaveClass('rail-collapsed');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(localStorage.getItem('agentdesk.railCollapsed')).toBe('0');
  });

  it('opens collapsed when the stored state says so', () => {
    localStorage.setItem('agentdesk.railCollapsed', '1');
    render(
      <div className="app">
        <Rail inboxWaiting={0} />
      </div>,
    );
    expect(document.querySelector('.app')).toHaveClass('rail-collapsed');
    const toggle = screen.getByRole('button', { name: 'Expand navigation' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });
});

describe('the hero band', () => {
  it('greets in one plain display line with the honest source line', () => {
    pinClock();
    render(<Dashboard data={DATA} onRefetch={async () => {}} onExpired={() => {}} />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      greetingFor(NOON),
    );
    // The eyebrow kicker is banned by the design contract.
    expect(document.querySelector('.hero-eyebrow')).toBeNull();
    expect(screen.getByText(dateLineFor(NOON))).toBeInTheDocument();
    expect(screen.getByText('Live: 1 of 3 sources connected.')).toBeInTheDocument();
  });

  it('says plainly when nothing is connected', () => {
    pinClock();
    const cold = {
      ...DATA,
      sources: { connected: 0, total: 3, items: [] },
      setup: COLD_SETUP,
    };
    render(<Dashboard data={cold} onRefetch={async () => {}} onExpired={() => {}} />);
    expect(screen.getByRole('region', { name: 'Needs a decision' })).toBeInTheDocument();
    // The setup steps live in the Get started strip (spec 022): the
    // workbook through the server's picker, the calendar through its walk.
    const strip = screen.getByRole('region', { name: 'Three steps and your desk is ready' });
    expect(within(strip).getByRole('button', { name: 'Open' })).toBeInTheDocument();
    expect(within(strip).getByRole('link', { name: 'Connect' })).toHaveAttribute('href', '/walkthrough/calendar');
    expect(screen.queryByText(/Not connected yet/)).toBeNull();
  });

  it('asks to turn research on when the payload says it is off', () => {
    pinClock();
    const off = { ...DATA, research: { enabled: false, lastAnsweredTs: null } };
    render(<Dashboard data={off} onRefetch={async () => {}} onExpired={() => {}} />);
    const region = screen.getByRole('region', { name: 'Needs a decision' });
    expect(region).toHaveTextContent('Turn research back on');
    expect(region).toHaveTextContent('off in settings');
    expect(screen.queryByText('Ask your first question')).toBeNull();
  });
});

describe('the research command bar', () => {
  it('disables Research until the question has a word', async () => {
    const user = userEvent.setup();
    render(<CommandBar busy={false} onAsk={vi.fn().mockResolvedValue(true)} />);
    const field = screen.getByLabelText('Research question');
    const send = screen.getByRole('button', { name: 'Research' });
    // An empty question has nothing to send, so the control says so
    // before it is pressed, not after a press that goes nowhere.
    expect(send).toBeDisabled();
    await user.type(field, '   ');
    expect(send).toBeDisabled();
    await user.type(field, 'Who sells to Meridian?');
    expect(send).toBeEnabled();
    await user.clear(field);
    expect(send).toBeDisabled();
  });

  it('sends nothing when Enter is pressed in a blank field', async () => {
    const onAsk = vi.fn().mockResolvedValue(true);
    const user = userEvent.setup();
    render(<CommandBar busy={false} onAsk={onAsk} />);
    const field = screen.getByLabelText('Research question');
    await user.type(field, '   {Enter}');
    expect(onAsk).not.toHaveBeenCalled();
    expect(field).toHaveValue('   ');
  });

  it('keeps the accessible name Research in both states', async () => {
    const user = userEvent.setup();
    render(<CommandBar busy={false} onAsk={vi.fn().mockResolvedValue(true)} />);
    const field = screen.getByLabelText('Research question');
    const send = screen.getByRole('button', { name: 'Research' });
    expect(send).toHaveAccessibleName('Research');
    await user.type(field, 'What changed this week?');
    expect(send).toBeEnabled();
    expect(send).toHaveAccessibleName('Research');
  });

  it('asks from a typed question when Research is pressed', async () => {
    const onAsk = vi.fn().mockResolvedValue(true);
    const user = userEvent.setup();
    render(<CommandBar busy={false} onAsk={onAsk} />);
    const field = screen.getByLabelText('Research question');
    await user.type(field, 'What changed this week?');
    await user.click(screen.getByRole('button', { name: 'Research' }));
    expect(onAsk).toHaveBeenCalledWith('What changed this week?');
  });

  it('asks on Enter and clears only when answered', async () => {
    const onAsk = vi.fn().mockResolvedValue(true);
    const user = userEvent.setup();
    render(<CommandBar busy={false} onAsk={onAsk} />);
    const field = screen.getByLabelText('Research question');
    await user.type(field, 'Who sells to Meridian?{Enter}');
    expect(onAsk).toHaveBeenCalledWith('Who sells to Meridian?');
    expect(await screen.findByLabelText('Research question')).toHaveValue('');
  });

  it('keeps the question when the ask did not answer', async () => {
    const onAsk = vi.fn().mockResolvedValue(false);
    const user = userEvent.setup();
    render(<CommandBar busy={false} onAsk={onAsk} />);
    const field = screen.getByLabelText('Research question');
    await user.type(field, 'Partial context{Enter}');
    expect(await screen.findByLabelText('Research question')).toHaveValue('Partial context');
  });

  it('does not ask on Shift+Enter', async () => {
    const onAsk = vi.fn().mockResolvedValue(true);
    const user = userEvent.setup();
    render(<CommandBar busy={false} onAsk={onAsk} />);
    const field = screen.getByLabelText('Research question');
    await user.type(field, 'a{Shift>}{Enter}{/Shift}');
    expect(onAsk).not.toHaveBeenCalled();
  });

  it('names the research field and uses the search mark', () => {
    render(<CommandBar busy={false} onAsk={vi.fn().mockResolvedValue(true)} />);
    const field = screen.getByLabelText('Research question');
    expect(field).toHaveAttribute('name', 'question');
    expect(field).toHaveAttribute('autocomplete', 'off');
    const mark = document.querySelector('.cmd-icon');
    expect(mark?.querySelector('circle')).not.toBeNull();
    expect(mark?.innerHTML ?? '').not.toContain('M12 3');
  });

  it('renders a real disabled send button and no effect canvases', () => {
    const onAsk = vi.fn().mockResolvedValue(true);
    render(<CommandBar busy onAsk={onAsk} />);
    expect(screen.getByRole('button', { name: /Research/i })).toBeDisabled();
    expect(document.querySelector('.cmd canvas')).toBeNull();
  });

  it('states the pause instead of inviting a question when research is off', () => {
    const onAsk = vi.fn().mockResolvedValue(true);
    render(<CommandBar busy={false} disabled onAsk={onAsk} />);
    expect(screen.getByLabelText('Research question')).toBeDisabled();
    expect(screen.getByRole('button', { name: /Research/i })).toBeDisabled();
    expect(document.querySelector('.cmd-hint')).toHaveTextContent(
      'Research is turned off in settings.',
    );
    expect(onAsk).not.toHaveBeenCalled();
  });
});

describe('the centered app states', () => {
  it('holds the bento skeleton and a quiet loading line while the payload arrives', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => {})),
    );
    render(<App />);
    const status = await screen.findByRole('status');
    expect(status).toHaveTextContent('Reading the dashboard…');
    expect(status).toHaveAttribute('aria-busy', 'true');
    // The shell and the brief's geometry, not a centered text card.
    const main = document.getElementById('dashboard-main');
    expect(main).toHaveAttribute('aria-busy', 'true');
    expect(document.querySelector('.brief')).not.toBeNull();
    expect(document.querySelector('.cell-hero')).not.toBeNull();
    expect(document.querySelector('.center-card')).toBeNull();
  });

  it('shows the session-expired view on a 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 401 })),
    );
    render(<App />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Session required');
    expect(screen.getByRole('heading', { name: 'Session required' })).toHaveFocus();
    // A reload only leads back to the same refusal; the notice names the
    // next step instead of offering a button that cannot succeed.
    expect(alert).toHaveTextContent('Open Agent Desk from its shortcut to get a fresh link.');
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  });

  it('shows the load-failed view when the server is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 503, statusText: 'unavailable' })),
    );
    render(<App />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The dashboard did not load');
    expect(screen.getByRole('heading', { name: 'The dashboard did not load' })).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeEnabled();
  });

  it('renders the dashboard once the payload is in', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json(DATA),
      ),
    );
    render(<App />);
    // The rail and the greeting exist only in the dashboard tree, never
    // in a centered state.
    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument();
    expect(document.getElementById('dashboard-main')).toHaveAttribute('tabindex', '-1');
    expect(document.querySelector('.hero-title')).toHaveTextContent(
      greetingFor(new Date()),
    );
  });

  it('reports the dashboard view exactly once after the first load', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json(DATA));
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument();
    await waitFor(() => {
      const reports = fetchMock.mock.calls.filter(
        ([url]) => String(url) === '/api/dashboard/view',
      );
      expect(reports).toHaveLength(1);
      expect(reports[0][1]?.method).toBe('POST');
    });
    // The report never blocks the surface: the dashboard is still on screen.
    expect(document.querySelector('.hero-title')).toBeInTheDocument();
  });
});
