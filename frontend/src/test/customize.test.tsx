// The customize ticket's behavior suite (issue #66): the Customize
// affordance in the hero, the per-card controls (drag handle, Move
// up/down, Rename, Hide), the Hidden cards strip with Restore, and the
// pinned save model: every action POSTs the full desired layout to
// /api/layout immediately and the dashboard refetches; there is no
// separate Save step. Reordering is instant (no motion), so the suite
// drives it through the keyboard buttons and through HTML5 drag events.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import type { DashboardData, LayoutCardState } from '../types';

const SALES = 'Sales, last 24 hours';
const COMMITMENTS = "Today's key commitment";
const RESEARCH = 'Research';

const BASE: DashboardData = {
  version: '0.0.0-test',
  flags: { excelEnabled: false, calendarEnabled: false, endpointEnabled: false },
  sources: { connected: 1, total: 3, items: [] },
  sales: { enabled: true, mode: 'unconfigured', status: null },
  commitments: { enabled: true, mode: 'unavailable', status: null },
  research: { enabled: true, lastAnsweredTs: null },
  inbox: { waiting: 0 },
  skills: [],
  layout: { cards: [] },
  plugins: {
    cards: [{
      id: 'p1', title: 'Invoice tracker', version: '1.2.0', pilot: true,
      state: 'active', freshness: 'fresh', cause: '',
    }],
  },
};

const DEFAULT_LAYOUT: LayoutCardState[] = [
  { key: 'sales', hidden: false, title: null },
  { key: 'commitments', hidden: false, title: null },
  { key: 'research', hidden: false, title: null },
  { key: 'skills', hidden: false, title: null },
  { key: 'p1', hidden: false, title: null },
];

interface PostedLayout {
  url: string;
  body: { cards: LayoutCardState[] };
}

// A routed fetch mock that owns the layout the way the server does: GET
// /api/layout returns the full listing, POST /api/layout records and
// adopts the posted cards, GET /api/dashboard renders the payload from
// the same truth (visible cards only, plugin titles overridden).
// The dashboard payload the server would render for a layout: visible
// cards only, in order, plugin titles overridden.
function payloadFor(layout: LayoutCardState[], base: DashboardData = BASE): DashboardData {
  const titles = new Map(
    layout.filter((c) => c.title).map((c) => [c.key, c.title as string]),
  );
  return {
    ...base,
    layout: {
      cards: layout
        .filter((c) => !c.hidden)
        .map((c) => ({ key: c.key, title: c.title })),
    },
    plugins: {
      cards: base.plugins.cards.map((card) => ({
        ...card,
        title: titles.get(card.id) ?? card.title,
      })),
    },
  };
}

function bootLayoutServer(initial: LayoutCardState[] = DEFAULT_LAYOUT, base: DashboardData = BASE) {
  let layout = initial.map((c) => ({ ...c }));
  const posts: PostedLayout[] = [];
  const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const target = String(url);
    if (target === '/api/layout' && init?.method === 'POST') {
      const body = JSON.parse(String(init.body)) as { cards: LayoutCardState[] };
      posts.push({ url: target, body });
      layout = body.cards.map((c) => ({ ...c }));
      return Response.json({ cards: layout.map((c) => ({ ...c })) });
    }
    if (target === '/api/layout') {
      return Response.json({ cards: layout.map((c) => ({ ...c })) });
    }
    return Response.json(payloadFor(layout, base));
  });
  vi.stubGlobal('fetch', fetchMock);
  return { posts, fetchMock };
}

async function renderDashboard() {
  render(<App />);
  await screen.findByRole('navigation', { name: 'Main' });
}

async function enterCustomize() {
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'Customize' }));
  await screen.findByRole('button', { name: 'Done customizing' });
}

function cellTexts(): string[] {
  return Array.from(document.querySelectorAll('.cust-cell')).map(
    (cell) => cell.textContent ?? '',
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('entering and leaving customize', () => {
  it('shows per-card controls and reads the full layout', async () => {
    const { fetchMock } = bootLayoutServer();
    await renderDashboard();
    await enterCustomize();
    // The per-card controls exist for every rendered card, labelled
    // with the card's name: the grab handle, the keyboard movers, the
    // rename and hide actions.
    expect(
      screen.getByRole('button', { name: `Drag to reorder ${RESEARCH}` }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: `Move ${RESEARCH} up` })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: `Move ${RESEARCH} down` })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: `Rename ${RESEARCH}` })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: `Hide ${RESEARCH}` })).toBeInTheDocument();
    // The full listing (hidden cards included) came from /api/layout.
    expect(
      fetchMock.mock.calls.some(([u]) => String(u) === '/api/layout'),
    ).toBe(true);
  });

  it('disables the Move buttons at the ends of the order', async () => {
    bootLayoutServer();
    await renderDashboard();
    await enterCustomize();
    expect(screen.getByRole('button', { name: `Move ${SALES} up` })).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Move Invoice tracker down' }),
    ).toBeDisabled();
  });

  it('says so honestly when the layout read is unreachable', async () => {
    // The dashboard is on screen, but GET /api/layout rejects: the
    // server went away between the two calls.
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL) => {
      if (String(url) === '/api/layout') {
        throw new TypeError('network down');
      }
      return Response.json(payloadFor(DEFAULT_LAYOUT));
    }));
    await renderDashboard();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Customize' }));
    // The honest note shows and customize did not open; no unhandled
    // rejection, no half-open mode.
    expect(
      await screen.findByText(
        'The dashboard could not reach its own server; customize did not open.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Done customizing' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Customize' })).toBeInTheDocument();
  });

  it('returns the normal view on Done', async () => {
    bootLayoutServer();
    await renderDashboard();
    await enterCustomize();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Done customizing' }));
    expect(screen.queryByRole('button', { name: `Hide ${RESEARCH}` })).toBeNull();
    expect(screen.queryByRole('button', { name: `Drag to reorder ${RESEARCH}` })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Done customizing' })).toBeNull();
    // The hero's normal actions are back.
    expect(screen.getByRole('button', { name: 'Add plugin' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Customize' })).toBeInTheDocument();
  });
});

describe('renaming a card', () => {
  it('focuses the rename input, and Escape returns focus to the grip', async () => {
    bootLayoutServer();
    await renderDashboard();
    await enterCustomize();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: `Rename ${RESEARCH}` }));
    // The input takes focus on mount: activating Rename must not dump
    // keyboard users on the body.
    const field = screen.getByLabelText(`Title for ${RESEARCH}`);
    expect(field).toHaveFocus();
    await user.keyboard('{Escape}');
    // Escape closes the editor and hands focus back to the card's grip.
    expect(screen.queryByLabelText(`Title for ${RESEARCH}`)).toBeNull();
    expect(screen.getByRole('button', { name: `Drag to reorder ${RESEARCH}` })).toHaveFocus();
  });

  it('saves the custom title and the card carries it', async () => {
    const { posts } = bootLayoutServer();
    await renderDashboard();
    await enterCustomize();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: `Rename ${RESEARCH}` }));
    const field = screen.getByLabelText(`Title for ${RESEARCH}`);
    await user.clear(field);
    await user.type(field, 'Digging');
    await user.click(screen.getByRole('button', { name: 'Save title' }));
    // The full desired layout was posted, once, with the new title.
    const last = posts[posts.length - 1];
    expect(last.url).toBe('/api/layout');
    expect(last.body.cards).toHaveLength(5);
    expect(last.body.cards.find((c) => c.key === 'research')).toEqual({
      key: 'research', hidden: false, title: 'Digging',
    });
    // The refetched payload carries the title, and the card shows it.
    expect(await screen.findByRole('heading', { level: 2, name: 'Digging' })).toBeInTheDocument();
    // The customize controls now speak the new name.
    expect(screen.getByRole('button', { name: 'Hide Digging' })).toBeInTheDocument();
  });

  it('returns to the default title on a blank rename', async () => {
    const { posts } = bootLayoutServer([
      { key: 'sales', hidden: false, title: null },
      { key: 'commitments', hidden: false, title: null },
      { key: 'research', hidden: false, title: 'Digging' },
      { key: 'skills', hidden: false, title: null },
      { key: 'p1', hidden: false, title: null },
    ]);
    await renderDashboard();
    await enterCustomize();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Rename Digging' }));
    const field = screen.getByLabelText('Title for Digging');
    await user.clear(field);
    await user.click(screen.getByRole('button', { name: 'Save title' }));
    const last = posts[posts.length - 1];
    expect(last.body.cards.find((c) => c.key === 'research')?.title).toBeNull();
    expect(await screen.findByRole('heading', { level: 2, name: RESEARCH })).toBeInTheDocument();
  });
});

describe('hiding and restoring a card', () => {
  it('omits the hidden card, lists it in the strip, and restores it', async () => {
    const { posts } = bootLayoutServer();
    await renderDashboard();
    await enterCustomize();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: `Hide ${RESEARCH}` }));
    const hide = posts.find((p) => p.body.cards.some((c) => c.key === 'research' && c.hidden));
    expect(hide).toBeTruthy();
    // The card is gone from the bento, and the strip names it with a
    // Restore action: hiding is recoverable, never destructive.
    expect(screen.queryByRole('heading', { level: 2, name: RESEARCH })).toBeNull();
    const strip = screen.getByRole('region', { name: 'Hidden cards' });
    expect(strip).toHaveTextContent(RESEARCH);
    await user.click(screen.getByRole('button', { name: `Restore ${RESEARCH}` }));
    const restore = posts[posts.length - 1];
    expect(restore.body.cards.find((c) => c.key === 'research')?.hidden).toBe(false);
    expect(await screen.findByRole('heading', { level: 2, name: RESEARCH })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Hidden cards' })).toBeNull();
  });

  it('lands focus on the restored card once it is back on screen', async () => {
    bootLayoutServer();
    await renderDashboard();
    await enterCustomize();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: `Hide ${RESEARCH}` }));
    await screen.findByRole('region', { name: 'Hidden cards' });
    await user.click(screen.getByRole('button', { name: `Restore ${RESEARCH}` }));
    // The restored card is not in the bento until the refetched payload
    // lands; focus must wait for that moment, not fire at the optimistic
    // render and fall to the body.
    await screen.findByRole('heading', { level: 2, name: RESEARCH });
    await vi.waitFor(() => {
      expect(
        screen.getByRole('button', { name: `Drag to reorder ${RESEARCH}` }),
      ).toHaveFocus();
    });
  });
});

describe('reordering', () => {
  it('moves a card down with the keyboard button and the bento follows', async () => {
    const { posts } = bootLayoutServer();
    await renderDashboard();
    await enterCustomize();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: `Move ${SALES} down` }));
    const last = posts[posts.length - 1];
    expect(last.body.cards.map((c) => c.key)).toEqual([
      'commitments', 'sales', 'research', 'skills', 'p1',
    ]);
    // After the refetch the customize cells render in the new order:
    // commitments leads, sales second.
    await vi.waitFor(() => {
      expect(cellTexts()[0]).toContain(COMMITMENTS);
      expect(cellTexts()[1]).toContain(SALES);
    });
  });

  it('reorders by HTML5 drag and drop, instantly', async () => {
    const { posts } = bootLayoutServer();
    await renderDashboard();
    await enterCustomize();
    const grip = screen.getByRole('button', { name: `Drag to reorder ${RESEARCH}` });
    const dataTransfer = {
      effectAllowed: '',
      setData: vi.fn(),
      getData: () => 'research',
    };
    fireEvent.dragStart(grip, { dataTransfer });
    const salesGrip = screen.getByRole('button', { name: `Drag to reorder ${SALES}` });
    const salesCell = salesGrip.closest('.cust-cell') as Element;
    fireEvent.dragOver(salesCell, { dataTransfer });
    fireEvent.drop(salesCell, { dataTransfer });
    const last = posts[posts.length - 1];
    // Dropping Research onto Sales places Research at Sales's slot.
    expect(last.body.cards.map((c) => c.key)).toEqual([
      'research', 'sales', 'commitments', 'skills', 'p1',
    ]);
    await vi.waitFor(() => {
      expect(cellTexts()[0]).toContain(RESEARCH);
    });
  });
});

describe('the save model', () => {
  it('says so honestly and re-reads the server when a save fails', async () => {
    bootLayoutServer();
    await renderDashboard();
    await enterCustomize();
    // After the customize read, every layout POST fails at the network.
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const target = String(url);
      if (target === '/api/layout' && init?.method === 'POST') {
        throw new TypeError('network down');
      }
      if (target === '/api/layout') {
        return Response.json({ cards: DEFAULT_LAYOUT.map((c) => ({ ...c })) });
      }
      return Response.json(payloadFor(DEFAULT_LAYOUT));
    }));
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: `Move ${SALES} down` }));
    expect(
      await screen.findByText('The dashboard could not reach its own server; the layout was not saved.'),
    ).toBeInTheDocument();
    // The optimistic move is reverted to the server's truth.
    await vi.waitFor(() => {
      expect(cellTexts()[0]).toContain(SALES);
    });
  });
});

// The normal view (the Brief) must follow the same layout the customize
// grid follows: hiding a card removes its cell after Done, and the saved
// order is the order the plugin cells render in. A desk with three
// plugin cards (two digests and a page watch) makes both observable.
const PLUGIN_BASE: DashboardData = {
  ...BASE,
  plugins: {
    cards: [
      { ...BASE.plugins.cards[0], id: 'p1', title: 'Invoice tracker' },
      { id: 'competitor-watch', title: 'Competitor watch', version: '1.0.0', pilot: false, state: 'active', freshness: 'fresh', cause: '' },
      { id: 'p3', title: 'Notes digester', version: '1.0.0', pilot: false, state: 'active', freshness: 'fresh', cause: '' },
    ],
  },
};

const PLUGIN_LAYOUT: LayoutCardState[] = [
  { key: 'sales', hidden: false, title: null },
  { key: 'commitments', hidden: false, title: null },
  { key: 'research', hidden: false, title: null },
  { key: 'skills', hidden: false, title: null },
  { key: 'p1', hidden: false, title: null },
  { key: 'competitor-watch', hidden: false, title: null },
  { key: 'p3', hidden: false, title: null },
];

/** The lower row's cell texts, in render order: what Done must change. */
function briefCellTexts(): string[] {
  return Array.from(document.querySelectorAll('.brief > .cell')).map(
    (cell) => cell.textContent ?? '',
  );
}

describe('the normal view follows the layout', () => {
  it('hides the hidden card and keeps the saved order after Done', async () => {
    bootLayoutServer(PLUGIN_LAYOUT, PLUGIN_BASE);
    await renderDashboard();
    await enterCustomize();
    const user = userEvent.setup();
    // Reorder first, while both cards are visible: Notes digester is
    // dragged onto Invoice tracker's slot, so it takes the earlier place.
    const grip = screen.getByRole('button', { name: 'Drag to reorder Notes digester' });
    const dataTransfer = {
      effectAllowed: '',
      setData: vi.fn(),
      getData: () => 'p3',
    };
    fireEvent.dragStart(grip, { dataTransfer });
    const targetCell = screen.getByRole('button', { name: 'Drag to reorder Invoice tracker' })
      .closest('.cust-cell') as Element;
    fireEvent.dragOver(targetCell, { dataTransfer });
    fireEvent.drop(targetCell, { dataTransfer });
    await vi.waitFor(() => {
      expect(cellTexts().findIndex((text) => text.includes('Notes digester')))
        .toBeLessThan(cellTexts().findIndex((text) => text.includes('Invoice tracker')));
    });
    // Then hide the invoice tracker entirely.
    await user.click(screen.getByRole('button', { name: 'Hide Invoice tracker' }));
    await screen.findByRole('region', { name: 'Hidden cards' });
    await user.click(screen.getByRole('button', { name: 'Done customizing' }));

    // The normal view answers the clicks: the hidden card is gone (its
    // cell and its health row), and the plugin cells keep the dragged
    // order (the lower row's direct children, the health cell excluded).
    const cells = briefCellTexts();
    expect(cells.some((text) => text.includes('Invoice tracker'))).toBe(false);
    const pluginCells = Array.from(document.querySelectorAll('.brief > .cell-digest, .brief > .cell-watch'));
    expect(pluginCells.map((cell) => cell.textContent)).toEqual([
      expect.stringContaining('Notes digester'),
      expect.stringContaining('Competitor watch'),
    ]);
  });
});
