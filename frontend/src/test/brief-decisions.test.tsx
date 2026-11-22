// The Decisions cell (spec 016 §9.1): waiting recommendations take the
// cell over, setup rows hold it before anything is saved, and a desk that
// is set up says so plainly instead of inventing a row.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
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

afterEach(cleanup);

describe('the Decisions cell', () => {
  it('renders a waiting recommendation with its sample tag and actions', () => {
    show({ ...BASE, recommendations: [HALVORSEN] });
    expect(screen.getByText('Halvorsen Freight: December 15 (in 25 days)')).toBeInTheDocument();
    expect(screen.getByText('You told the desk this deadline; it is 25 days away.')).toBeInTheDocument();
    expect(screen.getByText('SAMPLE DATA')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Agents' })).toHaveAttribute('href', '/agents');
    expect(screen.getByRole('button', { name: 'Not now' })).toBeInTheDocument();
    expect(screen.queryByText('Connect a workbook')).not.toBeInTheDocument();
  });

  it('falls back to the setup decisions when there are none', () => {
    show(BASE);
    expect(screen.getByText('Connect a workbook')).toBeInTheDocument();
    expect(screen.getByText('Connect your calendar')).toBeInTheDocument();
    expect(screen.getByText('Ask your first question')).toBeInTheDocument();
    expect(screen.queryByText('Nothing needs a decision.')).not.toBeInTheDocument();
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
