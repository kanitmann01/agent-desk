// Ticket 06: wave 1 on the SPA. Each tile opens with its sitting delta at
// the top, the reading's lines carry the why drilldown behind a native
// disclosure, the falsify line prints as it came, and the desk keeps the
// delta on screen across the 8-second polls while the tile's content
// stands still. The insight block kind "delta" is not the plugin element
// kind "delta": every pin here rides InsightBlock shapes (block.kind plus
// block.text), never PluginElement.
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import PluginCardView from '../dashboard/PluginCardView';
import TrackerCard from '../dashboard/TrackerCard';
import type { DashboardData, InsightBlock, PluginCard } from '../types';

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const NOOP_REFETCH = async () => {};
const NOOP_EXPIRED = () => {};

const DELTA: InsightBlock = {
  kind: 'delta',
  text: 'Since you last looked: the change figure moved from -8% to +2%.',
};
const FALSIFY: InsightBlock = {
  kind: 'falsify',
  text: 'What would change my mind: a quarter where West books more than East while prices rise.',
};
const NOTE: InsightBlock = {
  kind: 'note',
  text: 'Only the rows under the chart were looked at.',
};
const RECEIPTS_WITH_WHY: InsightBlock = {
  kind: 'receipts',
  text: "Used: your chart preference · this card's rows.",
  why: [
    {
      claim: 'Booked fell 18 rows behind last month.',
      columns: ['Region', 'Booked'],
      cells: ['D14', 'D15'],
      rule: 'mean shift larger than 2 standard deviations',
      facts: [{ id: 12, source: 'sales workbook' }],
    },
    {
      claim: 'The reading also matched a desk entity.',
      facts: [{ entityId: 4, name: 'West Ltd', factCount: 3 }],
    },
  ],
};

const TRACKER = {
  name: 'Q4 bookings',
  value: '12,400',
  unit: 'GBP',
  delta: '+2%',
  direction: 'up',
  points: [12, 11, 10, 9],
  file: 'reports/q4-bookings.xlsx',
};

function pluginCard(overrides: Partial<PluginCard> & { payload: PluginCard['payload'] }): PluginCard {
  return {
    id: 'kpi-scorecard~main',
    title: 'KPI scorecard',
    version: '1.0.0',
    pilot: false,
    state: 'enabled',
    freshness: 'fresh',
    cause: '',
    pluginId: 'kpi-scorecard',
    instanceId: 'main',
    ...overrides,
  };
}

describe('the sitting delta at the top of a tile', () => {
  it('renders above the elements of a fresh plugin tile, with the reading lines below them in order', () => {
    const card = pluginCard({
      payload: {
        elements: [
          { kind: 'metric', label: 'Booked', value: '18' },
          { kind: 'text', text: 'West carries most of the quarter.' },
        ],
        insight: {
          status: 'ok',
          source: 'local',
          blocks: [DELTA, RECEIPTS_WITH_WHY, FALSIFY, NOTE],
        },
      },
    });
    const { container } = render(<PluginCardView card={card} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    expect(screen.getByText(DELTA.text)).toBeInTheDocument();
    const banner = screen.getByText(DELTA.text);
    const figure = screen.getByText('18');
    expect(banner.compareDocumentPosition(figure) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    // The delta banner is the tile's first content: nothing the tile owns
    // sits above it.
    expect(container.firstElementChild?.textContent).toContain(DELTA.text);

    // receipts, falsify and note follow the elements, in the order the
    // server resolved them.
    expect(screen.getByText(RECEIPTS_WITH_WHY.text)).toBeInTheDocument();
    expect(screen.getByText(FALSIFY.text)).toBeInTheDocument();
    expect(screen.getByText(NOTE.text)).toBeInTheDocument();
    const receipts = screen.getByText(RECEIPTS_WITH_WHY.text);
    const falsify = screen.getByText(FALSIFY.text);
    const note = screen.getByText(NOTE.text);
    expect(receipts.compareDocumentPosition(falsify) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(falsify.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    // The delta block is drawn once, at the top: it never repeats below.
    expect(screen.getAllByText(DELTA.text)).toHaveLength(1);
  });

  it("renders an attention tile's delta even though the tile draws no elements or reading", () => {
    const card = pluginCard({
      freshness: 'attention',
      state: 'attention',
      cause: 'The data source could not be read just now.',
      payload: {
        elements: [],
        insight: {
          status: 'ok',
          source: 'local',
          blocks: [DELTA, RECEIPTS_WITH_WHY],
        },
      },
    });
    render(<PluginCardView card={card} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    expect(screen.getByText(DELTA.text)).toBeInTheDocument();
    expect(screen.getByText('The data source could not be read just now.')).toBeInTheDocument();
    // A tile that cannot stand behind its reading draws no reading lines.
    expect(screen.queryByText(RECEIPTS_WITH_WHY.text)).toBeNull();
    expect(screen.queryByText(FALSIFY.text)).toBeNull();
    expect(screen.queryByText(NOTE.text)).toBeNull();
  });

  it('renders above the figure of a live tracker tile', () => {
    const card = pluginCard({
      id: 'excel-report~q4',
      title: 'Q4 bookings',
      pluginId: 'excel-report',
      payload: {
        tracker: TRACKER,
        elements: [],
        insight: {
          status: 'ok',
          source: 'local',
          blocks: [DELTA, RECEIPTS_WITH_WHY, FALSIFY, NOTE],
        },
      },
    });
    const { container } = render(<TrackerCard card={card} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    expect(screen.getByText(DELTA.text)).toBeInTheDocument();
    const banner = screen.getByText(DELTA.text);
    const figure = screen.getByText('12,400');
    expect(banner.compareDocumentPosition(figure) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(container.firstElementChild?.textContent).toContain(DELTA.text);
    // The reading lines keep the tracker's own shape: the receipt visible,
    // the rest inside the disclosure, the delta never repeated there.
    expect(screen.getByText(RECEIPTS_WITH_WHY.text)).toBeInTheDocument();
    expect(screen.getByText('More of this reading')).toBeInTheDocument();
    expect(screen.getAllByText(DELTA.text)).toHaveLength(1);
  });

  it("renders an attention tracker tile's delta over its cause", () => {
    const card: PluginCard = {
      id: 'excel-report~q4',
      title: 'Q4 bookings',
      version: '0.1.0',
      pilot: false,
      state: 'attention',
      freshness: 'attention',
      cause: 'The workbook reports/q4-bookings.xlsx moved. Point the tracker at it again.',
      pluginId: 'excel-report',
      instanceId: 'q4',
      payload: {
        elements: [],
        insight: { status: 'ok', source: 'local', blocks: [DELTA] },
      },
    };
    render(<TrackerCard card={card} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    expect(screen.getByText(DELTA.text)).toBeInTheDocument();
    expect(
      screen.getByText('The workbook reports/q4-bookings.xlsx moved. Point the tracker at it again.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^Used/)).toBeNull();
  });

  it('draws nothing for a tile whose payload carries no delta block', () => {
    const card = pluginCard({
      payload: {
        elements: [{ kind: 'metric', label: 'Booked', value: '18' }],
        insight: { status: 'ok', source: 'local', blocks: [NOTE] },
      },
    });
    const { container } = render(<PluginCardView card={card} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    expect(container.querySelector('.w-delta-banner')).toBeNull();
    expect(screen.getByText(NOTE.text)).toBeInTheDocument();
  });
});

describe('the why drilldown on a receipts block', () => {
  it('opens a native disclosure holding claim, columns, cells, rule and citations', async () => {
    const user = userEvent.setup();
    const card = pluginCard({
      payload: {
        elements: [],
        insight: { status: 'ok', source: 'local', blocks: [RECEIPTS_WITH_WHY] },
      },
    });
    render(<PluginCardView card={card} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    const details = document.querySelector('details.w-why');
    expect(details).not.toBeNull();
    expect(details?.querySelector('summary')).toHaveTextContent('Why');
    // Closed until asked, native markup, zero script.
    expect((details as HTMLDetailsElement).open).toBe(false);
    await user.click(screen.getByText('Why'));
    expect((details as HTMLDetailsElement).open).toBe(true);
    expect(details?.textContent).toContain('Booked fell 18 rows behind last month.');
    expect(details?.textContent).toContain('Columns: Region, Booked');
    expect(details?.textContent).toContain('Cells: D14, D15');
    expect(details?.textContent).toContain('Rule: mean shift larger than 2 standard deviations');
    // Citations name the fact's id and source (or the desk entity's name
    // and count), never a fact's text.
    expect(details?.textContent).toContain('Fact 12');
    expect(details?.textContent).toContain('sales workbook');
    expect(details?.textContent).toContain('West Ltd');
    expect(details?.textContent).toContain('3 notes');
  });

  it('omits the disclosure from a receipts block that carries no why', () => {
    const card = pluginCard({
      payload: {
        elements: [],
        insight: {
          status: 'ok',
          source: 'local',
          blocks: [{ kind: 'receipts', text: "Used the defaults; read only this card's rows." }],
        },
      },
    });
    render(<PluginCardView card={card} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    expect(document.querySelector('details.w-why')).toBeNull();
    expect(screen.getByText("Used the defaults; read only this card's rows.")).toBeInTheDocument();
  });
});

describe('the falsify line under a research reading', () => {
  it("prints the server's sentence on a research tile and offers its press", () => {
    const card = pluginCard({
      id: 'research-brief~main',
      title: 'Research brief',
      payload: {
        elements: [{ kind: 'text', text: 'Hybrid work reduced measured output per the stored answer.' }],
        insight: {
          status: 'ok',
          source: 'local',
          blocks: [RECEIPTS_WITH_WHY, FALSIFY],
          press: {
            label: 'Check counter-evidence',
            route: '/api/insight/draft',
            kind: 'check-counter',
            text: 'Stored answer summary and its criterion, bounded.',
          },
        },
      },
    });
    render(<PluginCardView card={card} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    expect(screen.getByText(FALSIFY.text)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check counter-evidence' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Stage as a reply card' })).toBeNull();
  });
});

describe('the counter-evidence press', () => {
  const COUNTER_CARD = pluginCard({
    id: 'research-brief~main',
    title: 'Research brief',
    payload: {
      elements: [{ kind: 'text', text: 'Hybrid work reduced measured output per the stored answer.' }],
      insight: {
        status: 'ok',
        source: 'local',
        blocks: [FALSIFY],
        press: {
          label: 'Check counter-evidence',
          route: '/api/insight/draft',
          kind: 'check-counter',
          text: 'Stored answer summary and its criterion, bounded.',
        },
      },
    },
  });

  const COUNTER_ANSWER = {
    status: 'draft',
    text: 'The strongest opposing evidence is the office-first firms with the same drop.',
    source: 'model',
    disclosure: [
      "Sends: the stored answer summary and the desk's falsification criterion.",
      'Does not send: your workbook, your mail, your calendar, or any memory.',
    ],
    note: '',
  };

  it('names its phase while working, then draws the answer and the disclosure in place', async () => {
    const user = userEvent.setup();
    const calls: { url: string; body: Record<string, unknown> }[] = [];
    let release: () => void = () => {};
    const gate = new Promise<void>((resolveGate) => {
      release = resolveGate;
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: { body?: string }) => {
        calls.push({ url: String(url), body: JSON.parse(init?.body ?? '{}') as Record<string, unknown> });
        await gate;
        return Promise.resolve({ ok: true, status: 200, json: async () => COUNTER_ANSWER });
      }),
    );
    render(<PluginCardView card={COUNTER_CARD} onRefetch={NOOP_REFETCH} onExpired={NOOP_EXPIRED} />);

    await user.click(screen.getByRole('button', { name: 'Check counter-evidence' }));
    // The pending verb is the check's own, not the draft's or the range's.
    await waitFor(() => expect(screen.getByText('Checking the counter-evidence...')).toBeInTheDocument());
    await act(async () => {
      release();
    });

    expect(await screen.findByText(COUNTER_ANSWER.text)).toBeInTheDocument();
    expect(screen.getByText(COUNTER_ANSWER.disclosure[0])).toBeInTheDocument();
    expect(screen.getByText(COUNTER_ANSWER.disclosure[1])).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Stage as a reply card' })).toBeNull();
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe('/api/insight/draft');
    // The press travels verbatim: kind and text, nothing assembled.
    expect(calls[0].body).toEqual({
      kind: 'check-counter',
      text: 'Stored answer summary and its criterion, bounded.',
    });
  });

  it("announces the check's own phase, pending verb and done outcome", () => {
    const source = readFileSync(resolve(here, '..', 'dashboard', 'PluginCardView.tsx'), 'utf8');
    expect(source).toContain("'Checking the counter-evidence'");
    expect(source).toContain("'Checking the counter-evidence...'");
    expect(source).toContain("'Counter-evidence checked'");
    // The desk's vocabulary: never widget, never Hermes (whole words, so
    // an identifier such as WidgetCard does not read as copy).
    expect(source).not.toMatch(/\bwidget\b|\bHermes\b/i);
  });
});

// The sitting stability rule (spec 033): the SPA reports the view once per
// sitting, so the polls that follow answer without the delta block. The
// screen keeps the line the sitting opened with until the tile's own
// content changes, then replaces or clears it.
describe('the sitting delta across the 8-second polls', () => {
  const CARD_ID = 'kpi-scorecard~main';

  function desk(blocks: InsightBlock[], elementText: string): DashboardData {
    return {
      version: '0.0.0-test',
      flags: { excelEnabled: false, calendarEnabled: false, endpointEnabled: false },
      sources: { connected: 0, total: 1, items: [] },
      sales: { enabled: true, mode: 'unconfigured', status: null },
      commitments: { enabled: true, mode: 'unavailable', status: null },
      research: { enabled: true, lastAnsweredTs: null },
      inbox: { waiting: 0 },
      skills: [],
      layout: { cards: [{ key: CARD_ID, title: null }] },
      plugins: {
        cards: [
          pluginCard({
            payload: {
              elements: [{ kind: 'text', text: elementText }],
              insight: { status: 'ok', source: 'local', blocks },
            },
          }),
        ],
      },
    };
  }

  async function tick(): Promise<void> {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
  }

  it("keeps the line while the tile's content stands still, then clears or replaces it on a change", async () => {
    vi.useFakeTimers();
    const first = desk([DELTA, RECEIPTS_WITH_WHY], 'West carries most of the quarter.');
    let reads = 0;
    const responses: DashboardData[] = [
      // The poll after the view report: same content, the server no longer
      // repeats the delta.
      desk([RECEIPTS_WITH_WHY], 'West carries most of the quarter.'),
      // New content, no delta yet: the stale line goes.
      desk([RECEIPTS_WITH_WHY], 'North now carries most of the quarter.'),
      // Newer content with its own delta: the new line replaces it.
      desk(
        [
          { kind: 'delta', text: 'Since you last looked: the top region changed.' },
          RECEIPTS_WITH_WHY,
        ],
        'East now carries most of the quarter.',
      ),
    ];
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (String(url) !== '/api/dashboard') return Promise.resolve(Response.json({}));
        const answer = reads === 0 ? first : responses[reads - 1];
        reads += 1;
        return Promise.resolve(Response.json(answer));
      }),
    );
    render(<App />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // The sitting opens with the server's delta.
    expect(screen.getByText(DELTA.text)).toBeInTheDocument();

    // First poll: the payload no longer carries the delta, but the tile's
    // content stood still, so the line the sitting opened with stays.
    await tick();
    expect(screen.getByText(DELTA.text)).toBeInTheDocument();
    expect(screen.getByText(RECEIPTS_WITH_WHY.text)).toBeInTheDocument();

    // Second poll: the tile's content changed and no delta arrived, so
    // the stale line clears.
    await tick();
    expect(screen.queryByText(DELTA.text)).toBeNull();
    expect(screen.getByText('North now carries most of the quarter.')).toBeInTheDocument();

    // Third poll: newer content carries its own delta, which replaces the
    // cleared one.
    await tick();
    expect(screen.getByText('Since you last looked: the top region changed.')).toBeInTheDocument();
    expect(screen.queryByText(DELTA.text)).toBeNull();
  });
});
