// The Decisions cell (spec 016 §9.1): waiting recommendations take the
// cell over, setup rows hold it before anything is saved, and a desk that
// is set up says so plainly instead of inventing a row.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Brief from '../dashboard/Brief';
import type { DashboardData, Recommendation } from '../types';

const NOOP_REFETCH = async () => {};
const NOOP_EXPIRED = () => {};

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

/** The source table of a desk whose AI key is saved: the hub can serve a call. */
const AI_SAVED: DashboardData['sources'] = {
  connected: 1,
  total: 3,
  items: [{ id: 'research-endpoint', status: 'connected', detail: 'AI connected.' }],
};

const HALVORSEN: Recommendation = {
  cardId: 'card-1',
  title: 'Halvorsen Freight: December 15 (in 25 days)',
  why: 'You told the desk this deadline; it is 25 days away.',
  whySource: 'rule',
  score: null,
  due: '2026-12-15',
  href: '/agents',
  actionLabel: 'Open Agents',
  sample: true,
  cites: [3],
};

function show(data: DashboardData) {
  render(<Brief data={data} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('the Decisions cell', () => {
  it('renders a waiting recommendation with its sample tag and actions', () => {
    show({ ...BASE, recommendations: [HALVORSEN] });
    expect(screen.getByText('Halvorsen Freight: December 15 (in 25 days)')).toBeInTheDocument();
    expect(screen.getByText('You told the desk this deadline; it is 25 days away.')).toBeInTheDocument();
    expect(screen.getByText('SAMPLE DATA')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Open Agents' });
    expect(link).toHaveAttribute('href', '/agents');
    const actions = link.closest('.decision-actions');
    expect(actions).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Not now' }).closest('.decision-actions')).toBe(actions);
    expect(screen.queryByText('Connect a workbook')).not.toBeInTheDocument();
  });

  it('holds the first question until the AI key is saved, and leaves the steps to the strip', () => {
    show(BASE);
    // The AI key is the one thing every model call needs (spec 022): the
    // first question waits for it instead of inviting an error. The setup
    // steps themselves live in the Get started strip, so this cell does
    // not repeat them.
    expect(screen.queryByText('Ask your first question')).not.toBeInTheDocument();
    expect(screen.queryByText('Add your AI key')).not.toBeInTheDocument();
    expect(screen.queryByText('Connect a workbook')).not.toBeInTheDocument();
    expect(screen.getByText('Nothing needs a decision.')).toBeInTheDocument();
  });

  it('offers the first question once the AI key is saved', () => {
    show({ ...BASE, sources: AI_SAVED });
    expect(screen.queryByText('Add your AI key')).not.toBeInTheDocument();
    expect(screen.getByText('Ask your first question')).toBeInTheDocument();
  });

  it('links the overflow line to the inbox', () => {
    const rows = [1, 2, 3, 4].map((n) => ({ ...HALVORSEN, cardId: `card-${n}` }));
    show({ ...BASE, recommendations: rows });
    expect(screen.getByRole('link', { name: '1 more in inbox' })).toHaveAttribute('href', '/inbox');
  });

  it('keeps the row and says so when a dismiss fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })));
    show({ ...BASE, recommendations: [HALVORSEN] });
    fireEvent.click(screen.getByRole('button', { name: 'Not now' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not dismiss that decision.');
    expect(screen.getByText('Halvorsen Freight: December 15 (in 25 days)')).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it('does not present a stale delta as today’s move', () => {
    show({
      ...BASE,
      sales: {
        enabled: true,
        mode: 'live',
        status: {
          configured: true,
          state: 'stale',
          delta: { added: [['Acme - 1', 'EMEA', 'Proposal', 1000, '2026-12-01']], removed: [] },
        },
      },
      commitments: { enabled: true, mode: 'live', status: { state: 'clear' } },
      research: { enabled: true, lastAnsweredTs: 1_700_000_000 },
    });
    expect(screen.queryByText('Acme')).not.toBeInTheDocument();
    expect(screen.getByText('No deal has moved in the last 24 hours.')).toBeInTheDocument();
  });

  it('shows the staged update banner above the grid', () => {
    show({
      ...BASE,
      update: {
        banner: 'Version 0.1.1 is ready. Restart Agent Desk from its shortcut to switch.',
        available: '0.1.1',
        autoUpdate: true,
        channelSet: true,
        lastResult: 'staged',
      },
    });
    expect(screen.getByRole('status')).toHaveTextContent(
      'Version 0.1.1 is ready. Restart Agent Desk from its shortcut to switch.',
    );
  });

  it('shows the empty state once the desk is set up', () => {
    show({
      ...BASE,
      sources: AI_SAVED,
      sales: {
        enabled: true,
        mode: 'live',
        status: { configured: true, state: 'first' },
      },
      commitments: { enabled: true, mode: 'live', status: { state: 'clear' } },
      research: { enabled: true, lastAnsweredTs: 1_700_000_000 },
      agentLoop: { lastRunTs: 1_700_000_000, nextRunTs: null, enabled: true },
    });
    expect(screen.getByText('Nothing needs a decision.')).toBeInTheDocument();
    expect(screen.queryByText('Connect a workbook')).not.toBeInTheDocument();
    expect(screen.queryByText('Connect your calendar')).not.toBeInTheDocument();
  });
});

describe('the desk action line (spec 023)', () => {
  const view = (lastRunTs: number | null) =>
    render(<Brief data={{ ...BASE, agentLoop: { lastRunTs, nextRunTs: null, enabled: true } }} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

  it('names the desk action when a poll brings a stamp the page has not shown', () => {
    const brief = view(null);
    // No pass had run when the page opened: nothing to name yet.
    expect(screen.queryByText('The desk checked your sources.')).toBeNull();
    // The poll lands the first pass: the stamp moves and the line says so.
    brief.rerender(<Brief data={{ ...BASE, agentLoop: { lastRunTs: 1_700_000_000, nextRunTs: null, enabled: true } }} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    expect(screen.getByRole('status')).toHaveTextContent('The desk checked your sources.');
    // An unrelated re-render on the same payload keeps the line up.
    brief.rerender(<Brief data={{ ...BASE, agentLoop: { lastRunTs: 1_700_000_000, nextRunTs: null, enabled: true } }} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);
    expect(screen.getByRole('status')).toHaveTextContent('The desk checked your sources.');
  });

  it('never names the pass the page opened with', () => {
    view(1_700_000_000);
    expect(screen.queryByText('The desk checked your sources.')).toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
  });
});
