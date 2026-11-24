// The Memory page's knowledge graph: drawn from the payload the server
// sends, keyboard-driven, provenance on select, a list on narrow
// screens and a designed empty state. The fetch is the only fake.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MemoryGraph from '../memory/MemoryGraph';
import { ENTITY_MAX, LABEL_INSET, PILL, PILL_MAX, SPACE, fitLabel, layoutGraph, lineage, neighbourFor } from '../memory/layout';
import type { MemoryGraphData } from '../memory/types';

const DAY = 86_400;
const pipeline = (counts: number[]): MemoryGraphData['pipeline'] =>
  (['retain', 'extract', 'approve', 'store', 'link', 'reflect'] as const).map((step, i) => ({
    step, count: counts[i], text: `${step} words`,
  }));

const bank: MemoryGraphData = {
  status: 'ok',
  semantic: false,
  truncated: false,
  pipeline: pipeline([1, 1, 1, 2, 1, 1]),
  nodes: [
    { id: 'origin:retain', kind: 'origin', label: 'Save to memory', text: 'Saved conversations.', steps: [] },
    { id: 'origin:page', kind: 'origin', label: 'Memory page', text: 'Typed facts.', steps: [] },
    { id: 'source:1', kind: 'source', label: 'Call with Dana', text: 'Call with Dana about Halvorsen.', steps: [], speaker: 'You' },
    {
      id: 'fact:1', kind: 'fact', label: 'Halvorsen renews by Dec 15', text: 'Halvorsen renews by Dec 15',
      factKind: 'world', createdTs: 1_800_000_000, occurredTs: 1_800_000_000 - DAY, origin: 'origin:retain',
      steps: [
        { step: 'retain', ts: 1_800_000_000 - 60, text: 'A conversation excerpt (You) was saved to memory.' },
        { step: 'approve', ts: 1_800_000_000, text: 'You accepted a memory draft.' },
        { step: 'store', ts: 1_800_000_000, text: 'Written to memory.' },
        { step: 'link', ts: null, text: 'Linked to Halvorsen.' },
      ],
    },
    {
      id: 'fact:2', kind: 'fact', label: 'The office closes at six', text: 'The office closes at six',
      factKind: 'world', createdTs: 1_800_000_100, origin: 'origin:page',
      steps: [{ step: 'store', ts: 1_800_000_100, text: 'Typed on the Memory page and stored as written.' }],
    },
    { id: 'observation:1', kind: 'observation', label: 'Renewal is on track', text: 'Renewal is on track', confidence: 0.8, steps: [] },
    { id: 'entity:1', kind: 'entity', label: 'Halvorsen', text: 'Halvorsen', entityType: 'org', factCount: 1, steps: [] },
  ],
  edges: [
    { source: 'origin:retain', target: 'fact:1', type: 'wrote' },
    { source: 'origin:page', target: 'fact:2', type: 'wrote' },
    { source: 'source:1', target: 'fact:1', type: 'extracted' },
    { source: 'fact:1', target: 'entity:1', type: 'mentions' },
    { source: 'observation:1', target: 'fact:1', type: 'cites' },
    { source: 'fact:1', target: 'fact:2', type: 'temporal' },
  ],
};

function serve(payload: unknown, status = 200) {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL) => ({
    ok: status >= 200 && status < 300, status, json: async () => payload,
  }) as Response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('MemoryGraph', () => {
  it('draws every node the endpoint sends and counts the pipeline', async () => {
    const fetchMock = serve(bank);
    const { container } = render(<MemoryGraph initialWidth={1000} />);
    await screen.findByText('How this memory was made');
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/memory/graph');
    const ids = [...container.querySelectorAll('[data-node-id]')].map((n) => n.getAttribute('data-node-id'));
    expect(ids.sort()).toEqual(bank.nodes.map((n) => n.id).sort());
    const strip = screen.getByRole('list', { name: 'How a knowledge point is made' });
    expect(within(strip).getAllByRole('listitem')).toHaveLength(6);
    // Only link types present in the bank make the key; with semantic
    // memory off the key says why similar-meaning links are absent.
    const key = screen.getByRole('list', { name: 'Link types' });
    expect(within(key).queryByText('similar meaning')).toBeNull();
    expect(within(key).getByText(/need Semantic memory on/)).toBeTruthy();
    expect(within(key).getByText('cites')).toBeTruthy();
  });

  it('selecting a fact shows how it was made and what it touches', async () => {
    serve(bank);
    const user = userEvent.setup();
    render(<MemoryGraph initialWidth={1000} />);
    const fact = await screen.findByRole('button', { name: /Halvorsen renews by Dec 15/ });
    await user.click(fact);
    expect(fact.getAttribute('aria-pressed')).toBe('true');
    const panel = screen.getByRole('complementary', { name: 'Provenance' });
    expect(within(panel).getByText('How it was made')).toBeTruthy();
    expect(within(panel).getByText(/excerpt \(You\) was saved/)).toBeTruthy();
    expect(within(panel).getByText('You accepted a memory draft.')).toBeTruthy();
    expect(within(panel).getByRole('button', { name: /Halvorsen$/ })).toBeTruthy();
    await user.click(within(panel).getByRole('button', { name: 'Clear selection' }));
    expect(fact.getAttribute('aria-pressed')).toBe('false');
  });

  it('dims what is not in the selected lineage', async () => {
    serve(bank);
    const { container } = render(<MemoryGraph initialWidth={1000} />);
    const fact = await screen.findByRole('button', { name: /Halvorsen renews by Dec 15/ });
    fireEvent.click(fact);
    const dimmed = [...container.querySelectorAll('[data-node-id].is-dim')].map((n) => n.getAttribute('data-node-id'));
    expect(dimmed).toContain('origin:page');
    expect(dimmed).not.toContain('source:1');
  });

  it('moves with the arrow keys, selects with Enter and clears with Escape', async () => {
    serve(bank);
    render(<MemoryGraph initialWidth={1000} />);
    const fact = await screen.findByRole('button', { name: /Halvorsen renews by Dec 15/ });
    fact.focus();
    fireEvent.keyDown(fact, { key: 'ArrowRight' });
    const next = document.activeElement as Element;
    expect(next.getAttribute('data-node-id')).toBe('observation:1');
    fireEvent.keyDown(next, { key: 'Enter' });
    expect(next.getAttribute('aria-pressed')).toBe('true');
    fireEvent.keyDown(next, { key: 'Escape' });
    expect(next.getAttribute('aria-pressed')).toBe('false');
  });

  it('keeps one tab stop in the picture', async () => {
    serve(bank);
    const { container } = render(<MemoryGraph initialWidth={1000} />);
    await screen.findByText('How this memory was made');
    const stops = [...container.querySelectorAll('[data-node-id]')].filter((n) => n.getAttribute('tabindex') === '0');
    expect(stops).toHaveLength(1);
  });

  it('becomes a list on a narrow screen with provenance under the chosen row', async () => {
    serve(bank);
    const user = userEvent.setup();
    const { container } = render(<MemoryGraph initialWidth={340} />);
    await screen.findByText('How this memory was made');
    expect(container.querySelector('svg.mg-svg')).toBeNull();
    const row = screen.getByRole('button', { name: /The office closes at six/ });
    await user.click(row);
    const item = row.closest('li') as HTMLElement;
    expect(within(item).getByText('Typed on the Memory page and stored as written.')).toBeTruthy();
    expect(screen.getAllByRole('complementary', { name: 'Provenance' })).toHaveLength(1);
  });

  it('shows the designed empty state with the three ways in', async () => {
    serve({ ...bank, pipeline: pipeline([0, 0, 0, 0, 0, 0]), nodes: [], edges: [] });
    render(<MemoryGraph initialWidth={1000} />);
    await screen.findByText('No knowledge points yet');
    expect(screen.getByRole('link', { name: 'Assistant' }).getAttribute('href')).toBe('/assistant');
    expect(screen.getByRole('link', { name: 'Inbox' }).getAttribute('href')).toBe('/inbox');
    expect(screen.getByRole('link', { name: 'Settings' }).getAttribute('href')).toBe('/settings');
  });

  it('gives every fixed column and step label the full text as its title', async () => {
    serve(bank);
    const { container } = render(<MemoryGraph initialWidth={1000} />);
    await screen.findByText('How this memory was made');
    const columns = [...container.querySelectorAll('.mg-cols .mg-col-title')];
    expect(columns.map((column) => column.getAttribute('title')))
      .toEqual(['Came from', 'Facts', 'Observations', 'Entities']);
    const reflect = [...container.querySelectorAll('.mg-step-name')]
      .find((name) => name.textContent === 'Reflect');
    expect(reflect?.getAttribute('title')).toBe('Reflect');
  });

  it('gives the empty ghost columns their full headings as titles', async () => {
    serve({ ...bank, pipeline: pipeline([0, 0, 0, 0, 0, 0]), nodes: [], edges: [] });
    const { container } = render(<MemoryGraph initialWidth={1000} />);
    await screen.findByText('No knowledge points yet');
    const titles = [...container.querySelectorAll('.mg-empty-col .mg-col-title')];
    expect(titles.map((title) => title.getAttribute('title')))
      .toEqual(['Came from', 'Facts', 'Observations', 'Entities']);
  });

  it('makes every pipeline count a keyboard stop with its full value as a title', async () => {
    serve(bank);
    const { container } = render(<MemoryGraph initialWidth={1000} />);
    await screen.findByText('How this memory was made');
    const counts = [...container.querySelectorAll('.mg-step-count')];
    expect(counts).toHaveLength(6);
    for (const count of counts) {
      expect(count.getAttribute('tabindex')).toBe('0');
      expect(count.getAttribute('title')).toBe((count.textContent || '').trim());
    }
  });

  it('says so when the bank is locked', async () => {
    serve({ status: 'locked', error: 'the key file is missing' }, 423);
    render(<MemoryGraph initialWidth={1000} />);
    expect((await screen.findByRole('alert')).textContent).toMatch(/.+/);
  });
});

describe('graph layout', () => {
  it('orders facts in time and keeps columns apart', () => {
    const layout = layoutGraph(bank.nodes, bank.edges, 1000);
    const y = (id: string) => layout.placed.get(id)!.y;
    const col = (id: string) => layout.placed.get(id)!.column;
    expect(y('fact:1')).toBeLessThan(y('fact:2'));
    expect(col('source:1')).toBeLessThan(col('fact:1'));
    expect(col('fact:1')).toBeLessThan(col('observation:1'));
    expect(col('observation:1')).toBeLessThan(col('entity:1'));
  });

  it('stacks taller two-line pills and keeps edges on their centres', () => {
    const one = layoutGraph(bank.nodes, bank.edges, 1000);
    const two = layoutGraph(bank.nodes, bank.edges, 1000, { heights: new Map([['fact:1', PILL_MAX]]) });
    const first = two.placed.get('fact:1')!;
    const second = two.placed.get('fact:2')!;
    expect(first.height).toBe(PILL_MAX);
    expect(second.y - second.height / 2).toBe(first.y + first.height / 2 + SPACE);
    expect(second.y - one.placed.get('fact:2')!.y).toBe(PILL_MAX - PILL);
    // Clamped at two lines, whatever is measured.
    const tall = layoutGraph(bank.nodes, bank.edges, 1000, { heights: new Map([['fact:1', 90]]) });
    expect(tall.placed.get('fact:1')!.height).toBe(PILL_MAX);
  });

  it('sizes the entity column to its widest name, within bounds', () => {
    const fit = layoutGraph(bank.nodes, bank.edges, 1000, { entityText: 110 });
    expect(fit.placed.get('entity:1')!.width).toBe(110 + LABEL_INSET);
    const capped = layoutGraph(bank.nodes, bank.edges, 1000, { entityText: 900 });
    expect(capped.placed.get('entity:1')!.width).toBe(ENTITY_MAX);
    // The other columns share what is left and still meet the right edge.
    const last = [...fit.columns].pop()!;
    expect(last.x + last.width).toBeCloseTo(1000);
  });

  it('traces a fact back to its writer and excerpt but not to its siblings', () => {
    const lit = lineage('fact:1', bank.edges);
    expect(lit.has('origin:retain')).toBe(true);
    expect(lit.has('source:1')).toBe(true);
    expect(lit.has('entity:1')).toBe(true);
    expect(lit.has('origin:page')).toBe(false);
  });

  it('steps up, down and across columns', () => {
    const layout = layoutGraph(bank.nodes, bank.edges, 1000);
    expect(neighbourFor(layout, 'fact:1', 'ArrowDown')).toBe('fact:2');
    expect(neighbourFor(layout, 'fact:1', 'ArrowUp')).toBeNull();
    expect(neighbourFor(layout, 'entity:1', 'ArrowRight')).toBeNull();
  });

  it('fits a label to its pill with an ellipsis', () => {
    expect(fitLabel('short', 200)).toBe('short');
    const fitted = fitLabel('a very long label that cannot possibly fit', 120);
    expect(fitted.endsWith('\u2026')).toBe(true);
    expect(fitted.length).toBeLessThan(20);
  });
});
