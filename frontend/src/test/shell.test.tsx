// The shell ticket's behavior suite: the rail, the hero band, the
// research command bar and the centered app states, on the warm-paper
// system. Rendering-level checks: the effects wrappers are gone, the
// honest copy and the keyboard behaviors stay.
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import CommandBar from '../components/CommandBar';
import Dashboard from '../dashboard/Dashboard';
import Rail from '../dashboard/Rail';
import { dateLineFor, greetingFor } from '../fmt';
import type { DashboardData } from '../types';

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
  it('renders the brand as plain text and the nine entries', () => {
    render(<Rail inboxWaiting={2} />);
    // The brand carries no gradient: a plain span in the ink.
    const brand = document.querySelector<HTMLElement>('.brand-name');
    expect(brand).toHaveTextContent('Agent Desk');
    expect(brand?.style.backgroundImage).toBe('');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(nav).toHaveTextContent('Dashboard');
    expect(nav).toHaveTextContent('Inbox');
    expect(nav).toHaveTextContent('Assistant');
    expect(nav).toHaveTextContent('Settings');
    // Plugins is a real link to the plugins page now.
    expect(screen.getByText('Plugins').closest('a')).toHaveAttribute(
      'href',
      '/plugins',
    );
    // So is Peers (ticket #67): the peer-sharing page.
    expect(screen.getByText('Peers').closest('a')).toHaveAttribute(
      'href',
      '/peers',
    );
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('shows no inbox count when nothing waits', () => {
    render(<Rail inboxWaiting={0} />);
    expect(document.querySelector('.rail .count')).toBeNull();
  });

  it('links the four consolidation pages', () => {
    render(<Rail inboxWaiting={0} />);
    const nav = screen.getByRole('navigation', { name: 'Main' });
    for (const [name, href] of [
      ['Activity', '/activity'],
      ['Memory', '/memory'],
      ['Mail', '/mail'],
      ['Capabilities', '/capabilities'],
    ] as Array<[string, string]>) {
      const link = screen.getByRole('link', { name });
      expect(link).toHaveAttribute('href', href);
      expect(nav).toContainElement(link);
    }
  });

  it('carries a collapse control that announces its state', () => {
    render(<Rail inboxWaiting={0} />);
    const toggle = screen.getByRole('button', { name: 'Collapse navigation' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('collapses on click, keeps the count badge, and persists', async () => {
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
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(toggle).toHaveAttribute('aria-label', 'Expand navigation');
    // The inbox count stays visible while the labels hide: it is the
    // one signal worth keeping on a collapsed rail.
    expect(document.querySelector('.rail .count')).not.toBeNull();
    expect(localStorage.getItem('agentdesk.railCollapsed')).toBe('1');

    await user.click(toggle);
    expect(app).not.toHaveClass('rail-collapsed');
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
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
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
    };
    render(<Dashboard data={cold} onRefetch={async () => {}} onExpired={() => {}} />);
    expect(
      screen.getByText('Not connected yet: each card below has its own'),
    ).toBeInTheDocument();
    // "one-step" cannot break across the line: the phrase rides in a
    // nowrap span so a narrow greeting band never splits it.
    const nowrap = document.querySelector<HTMLElement>('.hero-live .nowrap');
    expect(nowrap).toHaveTextContent('one-step connect.');
  });
});

describe('the research command bar', () => {
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

  it('renders a real disabled send button and no effect canvases', () => {
    const onAsk = vi.fn().mockResolvedValue(true);
    render(<CommandBar busy onAsk={onAsk} />);
    expect(screen.getByRole('button', { name: /Research/i })).toBeDisabled();
    expect(document.querySelector('.cmd canvas')).toBeNull();
  });
});

describe('the centered app states', () => {
  it('holds a quiet loading line while the payload arrives', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => {})),
    );
    render(<App />);
    expect(await screen.findByText('Reading the dashboard.')).toBeInTheDocument();
  });

  it('shows the session-expired view on a 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 401 })),
    );
    render(<App />);
    expect(await screen.findByText('Session required')).toBeInTheDocument();
  });

  it('shows the load-failed view when the server is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 503, statusText: 'unavailable' })),
    );
    render(<App />);
    expect(await screen.findByText('The dashboard did not load')).toBeInTheDocument();
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
    expect(document.querySelector('.hero-title')).toHaveTextContent(
      greetingFor(new Date()),
    );
  });
});
