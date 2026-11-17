// The Memory page (src/memory/loop): review, capture settings, stored
// knowledge, removal with its preview, and undo. The server routes are
// the only fake: every write is checked by the URL and body it posts.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MemoryGraph from '../memory/MemoryGraph';
import MemoryLoop from '../memory/loop/MemoryLoop';
import { removedSummary } from '../memory/loop/copy';
import type { LoopState, RemovalPlan } from '../memory/loop/types';
import type { MemoryGraphData } from '../memory/types';

const NOW = Math.floor(Date.now() / 1000);

function state(overrides: Partial<LoopState> = {}): LoopState {
  return {
    status: 'ok',
    capture: {
      enabled: true,
      autoApprove: false,
      channels: [
        { id: 'assistant', label: 'Assistant', setting: 'memory_capture_assistant', on: true },
        { id: 'research', label: 'Research', setting: 'memory_capture_research', on: true },
      ],
    },
    extractor: { mode: 'rules', detail: 'No endpoint is saved.' },
    lastCapture: null,
    undoWindowS: 30,
    counts: { waiting: 1, facts: 2, standing: 2, replaced: 0, entities: 1, observations: 1, flagged: 0, sources: 1 },
    candidates: [{
      cardId: 'c1', type: 'fact', text: 'Acme moved the renewal to March 3.', title: 'Memory fact',
      createdTs: NOW, channel: 'assistant', channelLabel: 'Assistant', method: 'rules',
      entities: [{ name: 'Acme', type: 'org' }],
      excerpt: { id: 9, text: 'Acme moved the renewal to March 3.', speaker: 'You', createdTs: NOW },
    }],
    facts: [
      {
        id: 1, text: 'Acme renews in February.', kind: 'world', createdTs: NOW, occurredTs: null,
        origin: { id: 'page', label: 'Typed on this page', how: '' }, sample: false, sourceId: null, excerpt: null,
        entities: [{ id: 5, name: 'Acme' }], replacedBy: null, replaces: [], observationIds: [3],
      },
      {
        id: 2, text: 'Acme has 40 seats.', kind: 'world', createdTs: NOW, occurredTs: null,
        origin: { id: 'review:assistant', label: 'Assistant', how: 'You approved' }, sample: false, sourceId: 9,
        excerpt: null, entities: [{ id: 5, name: 'Acme' }], replacedBy: null, replaces: [], observationIds: [3],
      },
    ],
    entities: [{ id: 5, name: 'Acme', type: 'org', aliases: [], factCount: 2 }],
    sources: [{ id: 9, text: 'Acme has 40 seats.', speaker: 'You', channel: 'assistant', channelLabel: 'Assistant', createdTs: NOW, factIds: [2] }],
    observations: [{
      id: 3, text: 'Acme: renews in February; has 40 seats.', confidence: 0.7, factIds: [1, 2],
      createdTs: NOW, updatedTs: NOW, staleTs: null, entityId: 5, derived: 'consolidated',
    }],
    ...overrides,
  };
}

const graph: MemoryGraphData = {
  status: 'ok', semantic: false, truncated: false, pipeline: [],
  nodes: [
    { id: 'origin:page', kind: 'origin', label: 'Memory page', text: 'Typed facts.', steps: [] },
    {
      id: 'fact:1', kind: 'fact', label: 'Acme renews in February.', text: 'Acme renews in February.',
      factKind: 'world', createdTs: NOW, origin: 'origin:page', steps: [],
    },
    { id: 'entity:5', kind: 'entity', label: 'Acme', text: 'Acme', entityType: 'org', factCount: 2, steps: [] },
  ],
  edges: [
    { source: 'origin:page', target: 'fact:1', type: 'wrote' },
    { source: 'fact:1', target: 'entity:5', type: 'mentions' },
  ],
};

const plan: RemovalPlan = {
  target: { type: 'fact', id: 1, label: 'Acme renews in February.' },
  facts: [{ id: 1, text: 'Acme renews in February.' }],
  observationsRemoved: [{ id: 3, text: 'Acme: renews in February; has 40 seats.' }],
  observationsUpdated: [],
  observationsFlagged: [],
  entitiesRemoved: [],
  entitiesUpdated: [{ id: 5, name: 'Acme' }],
  factsRestored: [],
  sourcesRemoved: [],
};

type Call = { url: string; body: unknown };

// Routes answer by URL; GET /api/memory/loop answers the current state,
// which a test can swap to show what the page reads after a write.
function serve(initial: LoopState, extra: Record<string, unknown> = {}) {
  const calls: Call[] = [];
  let current: unknown = initial;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (init?.method === 'POST') calls.push({ url, body });
    let payload: unknown = { ok: true };
    if (url === '/api/memory/loop') payload = current;
    else if (url === '/api/memory/graph') payload = graph;
    else if (url in extra) payload = extra[url];
    return { ok: true, status: 200, json: async () => payload } as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls, set: (next: LoopState) => { current = next; } };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('MemoryLoop', () => {
  it('reads the loop and lays it out as capture, store, process and remove', async () => {
    serve(state());
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Memory' })).toBeTruthy();
    const flow = screen.getByRole('list', { name: 'How memory is built' });
    const steps = within(flow).getAllByRole('listitem');
    expect(steps.map((s) => s.querySelector('.ml-tag')?.textContent)).toEqual(['Capture', 'Store', 'Process', 'Remove']);
    expect(within(steps[0]).getByText('Rules')).toBeTruthy();
    expect(screen.getByText(/2 facts the assistant can recall, across 1 entity/)).toBeTruthy();
    expect(screen.getByText(/New facts wait for your review/)).toBeTruthy();
  });

  it('approves, rejects and edits a candidate through the inbox card routes', async () => {
    const { calls } = serve(state());
    const user = userEvent.setup();
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    const review = await screen.findByRole('region', { name: 'Review' });
    expect(within(review).getByText('Acme moved the renewal to March 3.', { selector: '.ml-cand-text' })).toBeTruthy();

    await user.click(within(review).getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(calls.map((c) => c.url)).toContain('/inbox/cards/c1/accept'));

    await user.click(within(review).getByRole('button', { name: 'Reject' }));
    await waitFor(() => expect(calls.map((c) => c.url)).toContain('/inbox/cards/c1/dismiss'));

    await user.click(within(review).getByRole('button', { name: 'Edit' }));
    const box = within(review).getByLabelText('Edit before saving');
    await user.clear(box);
    await user.type(box, 'Acme moved the renewal to March 10.');
    calls.length = 0;
    await user.click(within(review).getByRole('button', { name: 'Save edited' }));
    await waitFor(() => expect(calls.map((c) => c.url)).toEqual(['/inbox/cards/c1/edit', '/inbox/cards/c1/accept']));
    expect(calls[0].body).toEqual({ draft: 'Acme moved the renewal to March 10.' });
  });

  it('shows the excerpt a candidate came from', async () => {
    serve(state());
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    const review = await screen.findByRole('region', { name: 'Review' });
    expect(within(review).getByText('From what was said')).toBeTruthy();
    expect(within(review).getByText('Acme', { selector: '.ml-entity' })).toBeTruthy();
  });

  it('turns capture switches and the review mode through /settings/toggle', async () => {
    const { calls } = serve(state());
    const user = userEvent.setup();
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    const research = await screen.findByRole('switch', { name: /Research/ });
    expect(research.getAttribute('aria-checked')).toBe('true');
    await user.click(research);
    await user.click(screen.getByRole('radio', { name: 'Save automatically' }));
    // Already in review mode: choosing it again posts nothing.
    await user.click(screen.getByRole('radio', { name: 'Ask me first' }));
    await waitFor(() => expect(calls.map((c) => c.body)).toEqual([
      { key: 'memory_capture_research' }, { key: 'memory_auto_approve' },
    ]));
  });

  it('greys the channel switches when capture is off', async () => {
    const off = state({ capture: { ...state().capture, enabled: false } });
    serve(off);
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    const assistant = await screen.findByRole('switch', { name: /^Assistant/ });
    expect((assistant as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Capture is off/)).toBeTruthy();
  });

  it('switches tabs with the arrow keys and filters rows', async () => {
    serve(state());
    const user = userEvent.setup();
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    const facts = await screen.findByRole('tab', { name: /Facts/ });
    expect(facts.getAttribute('aria-selected')).toBe('true');
    const panel = screen.getByRole('tabpanel');
    expect(within(panel).getAllByRole('listitem')).toHaveLength(2);
    await user.type(screen.getByLabelText('Filter'), 'seats');
    expect(within(panel).getAllByRole('listitem')).toHaveLength(1);
    await user.clear(screen.getByLabelText('Filter'));
    facts.focus();
    fireEvent.keyDown(facts, { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: /Entities/ }).getAttribute('aria-selected')).toBe('true');
    expect(within(screen.getByRole('tabpanel')).getByRole('button', { name: 'Forget…' })).toBeTruthy();
    fireEvent.keyDown(screen.getByRole('tab', { name: /Entities/ }), { key: 'End' });
    expect(screen.getByRole('tab', { name: /Observations/ }).getAttribute('aria-selected')).toBe('true');
    expect(within(screen.getByRole('tabpanel')).getByText('Consolidated')).toBeTruthy();
  });

  it('previews a removal, removes on confirm, then offers undo', async () => {
    const removed = {
      facts: [1], observationsRemoved: [3], observationsFlagged: [], observationsUpdated: [],
      entitiesRemoved: [], sourcesRemoved: [], factsRestored: [],
    };
    const { calls, set } = serve(state(), {
      '/api/memory/remove/preview': { plan },
      '/api/memory/remove': { removed, undo: { token: 'tok', expiresTs: NOW + 30 } },
      '/api/memory/undo': { ok: true },
    });
    const user = userEvent.setup();
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    const panel = await screen.findByRole('tabpanel');
    const row = within(panel).getByText('Acme renews in February.').closest('li') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: 'Remove…' }));

    const dialog = await screen.findByRole('dialog', { name: 'Acme renews in February.' });
    expect(within(dialog).getByText('Observations removed')).toBeTruthy();
    expect(within(dialog).getByText('Acme: renews in February; has 40 seats.')).toBeTruthy();
    expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(calls.at(-1)).toEqual({ url: '/api/memory/remove/preview', body: { target: { type: 'fact', id: 1 } } });

    set(state({ facts: state().facts.slice(1), observations: [], counts: { ...state().counts, standing: 1, facts: 1, observations: 0 } }));
    await user.click(within(dialog).getByRole('button', { name: 'Remove 1 fact' }));
    const bar = await screen.findByText(/Removed 1 fact · 1 observation removed/);
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(within(screen.getByRole('tabpanel')).queryByText('Acme renews in February.')).toBeNull());

    set(state());
    await user.click(within(bar.closest('.ml-undo') as HTMLElement).getByRole('button', { name: 'Undo' }));
    expect(calls.at(-1)).toEqual({ url: '/api/memory/undo', body: { token: 'tok' } });
    expect(await screen.findByText(/Removal undone/)).toBeTruthy();
    expect(await within(screen.getByRole('tabpanel')).findByText('Acme renews in February.')).toBeTruthy();
  });

  it('closes the removal preview on Escape without writing', async () => {
    const { calls } = serve(state(), { '/api/memory/remove/preview': { plan } });
    const user = userEvent.setup();
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    await screen.findByRole('tabpanel');
    await user.click(screen.getAllByRole('button', { name: 'Remove…' })[0]);
    await screen.findByRole('dialog');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(calls.map((c) => c.url)).toEqual(['/api/memory/remove/preview']);
  });

  it('keeps a replaced fact on request', async () => {
    const replaced = state();
    replaced.facts[0] = { ...replaced.facts[0], replacedBy: 2 };
    const { calls } = serve(replaced);
    const user = userEvent.setup();
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    await user.click(await screen.findByRole('button', { name: 'Keep both' }));
    await waitFor(() => expect(calls.map((c) => c.url)).toContain('/api/memory/facts/1/keep'));
  });

  it('adds a typed fact, and says what to do when the box is empty', async () => {
    const { calls } = serve(state());
    const user = userEvent.setup();
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    const save = await screen.findByRole('button', { name: 'Save fact' });
    await user.click(save);
    expect(screen.getByText('Type the fact first, in one sentence.')).toBeTruthy();
    expect(calls).toHaveLength(0);
    await user.type(screen.getByLabelText('Fact'), 'The Acme renewal is due March 3.');
    await user.click(save);
    await waitFor(() => expect(calls).toEqual([{ url: '/memory/add', body: { text: 'The Acme renewal is due March 3.' } }]));
  });

  it('keeps Tab inside the removal preview', async () => {
    serve(state(), { '/api/memory/remove/preview': { plan } });
    const user = userEvent.setup();
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    await screen.findByRole('tabpanel');
    await user.click(screen.getAllByRole('button', { name: 'Remove…' })[0]);
    const dialog = await screen.findByRole('dialog');
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    const confirm = within(dialog).getByRole('button', { name: 'Remove 1 fact' });
    await user.tab();
    expect(document.activeElement).toBe(confirm);
    await user.tab();
    expect(document.activeElement).toBe(cancel);
  });

  it('says what went wrong when the state cannot be read', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) }) as Response));
    render(<MemoryLoop pollMs={0} graphWidth={900} />);
    expect((await screen.findByRole('alert')).textContent).toMatch(/session ended/);
  });
});

describe('removedSummary', () => {
  it('names what went and what else changed', () => {
    expect(removedSummary({
      facts: [1, 2], observationsRemoved: [], observationsFlagged: [7], observationsUpdated: [3],
      entitiesRemoved: [4], sourcesRemoved: [], factsRestored: [9],
    })).toBe('Removed 2 facts · 1 observation rewritten · 1 observation flagged · 1 entity forgotten · 1 older fact back in recall');
  });
});

describe('MemoryGraph inside the page', () => {
  it('drops its own header without chrome and hands removals to the page', async () => {
    serve(state());
    const onRemove = vi.fn();
    const user = userEvent.setup();
    render(<MemoryGraph chrome={false} initialWidth={1000} onRemove={onRemove} />);
    const fact = await screen.findByRole('button', { name: /Acme renews in February/ });
    expect(screen.queryByRole('list', { name: 'How a knowledge point is made' })).toBeNull();
    await user.click(fact);
    const panel = screen.getByRole('complementary', { name: 'Provenance' });
    await user.click(within(panel).getByRole('button', { name: 'Remove…' }));
    expect(onRemove).toHaveBeenCalledWith(expect.objectContaining({ id: 'fact:1' }));
  });

  it('selects the node the page asks it to focus', async () => {
    serve(state());
    render(<MemoryGraph chrome={false} initialWidth={1000} focusId="entity:5" onRemove={() => {}} />);
    const panel = await screen.findByRole('complementary', { name: 'Provenance' });
    expect(within(panel).getByRole('button', { name: 'Forget Acme…' })).toBeTruthy();
  });
});
