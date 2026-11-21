// Ticket 05: the workbook card draws the reading the server already drew:
// its appended elements through the same view the plugin card uses, the
// receipt line with the server's own words, and nothing at all when there is
// no reading to draw.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TrackerCard from '../dashboard/TrackerCard';
import type { PluginCard, PluginElement } from '../types';

const NOOP_REFETCH = async () => {};
const NOOP_EXPIRED = () => {};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TRACKER = {
  name: 'Q4 bookings',
  value: '12,400',
  unit: 'GBP',
  delta: '-8%',
  direction: 'down',
  points: [12, 11, 10, 9],
  file: 'reports/q4-bookings.xlsx',
};

// The reading the workbook family appends: two text elements, a checklist of
// the rows worth selecting, and one element of a kind this build has no view
// for (a newer server, a family added later).
const READING_CARD: PluginCard = {
  id: 'excel-report~q4',
  title: 'Q4 bookings',
  version: '0.1.0',
  pilot: false,
  state: 'enabled',
  freshness: 'fresh',
  cause: '',
  pluginId: 'excel-report',
  instanceId: 'q4',
  payload: {
    tracker: TRACKER,
    elements: [
      { kind: 'text', label: 'Reading', text: 'Booked is 18 rows behind last month, and West carries most of it.' },
      { kind: 'text', label: 'Chart', text: 'Booked by Region, drawn as a bar chart.' },
      {
        kind: 'checklist',
        title: 'Rows worth selecting',
        items: [{ text: 'Row 12: West' }, { text: 'Row 19: North' }],
      },
      { kind: 'mystery', label: 'Newer', text: 'A kind this build does not draw.' } as unknown as PluginElement,
    ],
    insight: {
      status: 'ok',
      source: 'local',
      preferences: ['chart'],
      note: 'Only the rows under the chart were looked at.',
      blocks: [
        { kind: 'receipts', text: "Used: your chart preference · memory (2 notes) · this card's rows." },
        { kind: 'note', text: 'Only the rows under the chart were looked at.' },
      ],
      press: null,
    },
  },
};

describe('the workbook card draws the reading', () => {
  it('renders the appended elements and the resolved lines under the figure', () => {
    render(<TrackerCard card={READING_CARD} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    expect(screen.getByText('Booked is 18 rows behind last month, and West carries most of it.')).toBeInTheDocument();
    expect(screen.getByText('Booked by Region, drawn as a bar chart.')).toBeInTheDocument();
    expect(screen.getByText('Rows worth selecting')).toBeInTheDocument();
    expect(screen.getByText('Row 12: West')).toBeInTheDocument();
    expect(screen.getByText('Row 19: North')).toBeInTheDocument();
    expect(
      screen.getByText("Used: your chart preference · memory (2 notes) · this card's rows."),
    ).toBeInTheDocument();
    // A note block prints the server's sentence as it came; there is no
    // second phrase table in this build to disagree with it.
    expect(screen.getByText('Only the rows under the chart were looked at.')).toBeInTheDocument();
    // An unknown kind draws nothing rather than an empty box.
    expect(screen.queryByText('A kind this build does not draw.')).toBeNull();
  });

  it('prints the defaults line the server resolved when no preference changed the reading', () => {
    const card: PluginCard = {
      ...READING_CARD,
      payload: {
        tracker: TRACKER,
        elements: [{ kind: 'text', label: 'Reading', text: 'Two regions carry the whole quarter.' }],
        insight: {
          status: 'ok',
          source: 'local',
          note: '',
          blocks: [{ kind: 'receipts', text: "Used the defaults; read only this card's rows." }],
          press: null,
        },
      },
    };
    render(<TrackerCard card={card} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    expect(screen.getByText('Two regions carry the whole quarter.')).toBeInTheDocument();
    expect(screen.getByText("Used the defaults; read only this card's rows.")).toBeInTheDocument();
    // The server resolved the line; this build draws one paragraph per block
    // and never a second line of its own.
    expect(screen.getAllByText(/^Used/)).toHaveLength(1);
  });

  it('names every input the defaults read, and counts memory the way the server does', () => {
    const card: PluginCard = {
      ...READING_CARD,
      payload: {
        tracker: TRACKER,
        elements: [{ kind: 'text', label: 'Reading', text: 'Dana is still waiting on the forecast.' }],
        insight: {
          status: 'ok',
          source: 'local',
          note: '',
          blocks: [{ kind: 'receipts', text: 'Used the defaults; read memory (1 note) and this calendar.' }],
          press: null,
        },
      },
    };
    render(<TrackerCard card={card} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    expect(screen.getByText('Used the defaults; read memory (1 note) and this calendar.')).toBeInTheDocument();
  });

  it('leaves an attention card exactly as it was', () => {
    const card: PluginCard = {
      id: 'excel-report~q4',
      title: 'Q4 bookings',
      version: '0.1.0',
      pilot: false,
      state: 'attention',
      freshness: 'attention',
      cause: 'The workbook reports/q4-bookings.xlsx moved. Point the tracker at it again.',
      payload: null,
    };
    render(<TrackerCard card={card} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    expect(
      screen.getByText('The workbook reports/q4-bookings.xlsx moved. Point the tracker at it again.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Set up' })).toBeInTheDocument();
    expect(screen.queryByText(/^Used/)).toBeNull();
  });
});
