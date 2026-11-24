// Feedback on every wait in the two memory islands: the 100 ms gate, the
// control's own busy state, the region placeholder from one second, the
// ten second slow line, in-place results and errors, stale refetches.
// Fake timers pin the gates; the fetch mock can hold each response.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MemoryGraph from '../memory/MemoryGraph';
import MemoryLoop from '../memory/loop/MemoryLoop';
import type { LoopState, RemovalPlan } from '../memory/loop/types';
import type { MemoryGraphData } from '../memory/types';

const NOW = Math.floor(Date.now() / 1000);

function state(overrides: Partial<LoopState> = {}): LoopState {
  const base: LoopState = {
    status: 'ok',
    capture: {
      enabled: true,
      autoApprove: false,
      channels: [
        { id: 'assistant', label: 'Assistant', setting: 'memory_capture_assistant', on: true },
        { id: 'research', label: 'Research', setting: 'memory_capture_research', on: true },
      ],
    },
    extractor: { mode: 'model', detail: 'Your AI is connected.' },
    lastCapture: null,
    undoWindowS: 30,
    counts: { waiting: 3, facts: 2, standing: 2, replaced: 0, entities: 1, observations: 1, flagged: 0, sources: 1 },
    candidates: [
      {
        cardId: 'c1', type: 'fact', text: 'Acme moved the renewal to March 3.', title: 'Memory fact',
        createdTs: NOW, channel: 'assistant', channelLabel: 'Assistant', method: 'rules',
        entities: [{ name: 'Acme', type: 'org' }], excerpt: null,
      },
      {
        cardId: 'c2', type: 'fact', text: 'Acme has 40 seats.', title: 'Memory fact',
        createdTs: NOW, channel: 'assistant', channelLabel: 'Assistant', method: 'rules',
        entities: [{ name: 'Acme', type: 'org' }], excerpt: null,
      },
      {
        cardId: 'c3', type: 'fact', text: 'Acme renews in February.', title: 'Memory fact',
        createdTs: NOW, channel: 'assistant', channelLabel: 'Assistant', method: 'rules',
        entities: [{ name: 'Acme', type: 'org' }], excerpt: null,
      },
    ],
    facts: [
      {
        id: 1, text: 'Acme renews in February.', kind: 'world', createdTs: NOW, occurredTs: null,
        origin: { id: 'page', label: 'Typed on this page', how: '' }, sample: false, sourceId: null, excerpt: null,
        entities: [{ id: 5, name: 'Acme' }], replacedBy: 2, replaces: [], observationIds: [3],
      },
      {
        id: 2, text: 'Acme has 40 seats.', kind: 'world', createdTs: NOW, occurredTs: null,
        origin: { id: 'review:assistant', label: 'Assistant', how: 'You approved' }, sample: false, sourceId: 9,
        excerpt: null, entities: [{ id: 5, name: 'Acme' }], replacedBy: null, replaces: [1], observationIds: [3],
      },
    ],
    entities: [{ id: 5, name: 'Acme', type: 'org', aliases: [], factCount: 2 }],
    sources: [{ id: 9, text: 'Acme has 40 seats.', speaker: 'You', channel: 'assistant', channelLabel: 'Assistant', createdTs: NOW, factIds: [2] }],
    observations: [{
      id: 3, text: 'Acme renews in February and has 40 seats.', confidence: 0.7, factIds: [1, 2],
      createdTs: NOW, updatedTs: NOW, staleTs: null, entityId: 5, entityName: 'Acme', derived: 'consolidated',
      method: 'model',
    }],
  };
  return { ...base, ...overrides };
}

const graph: MemoryGraphData = {
  status: 'ok', semantic: false, truncated: false,
  pipeline: (['retain', 'extract', 'approve', 'store', 'link', 'reflect'] as const).map((step) => ({
    step, count: 1, text: `${step} words`,
  })),
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
  observationsRemoved: [], observationsUpdated: [], observationsFlagged: [],
  entitiesRemoved: [], entitiesUpdated: [], factsRestored: [], sourcesRemoved: [],
};

type Gate = { url: string; body: unknown; ok: (data?: unknown) => void; fail: (message?: string) => void };

/** A fetch mock whose GETs answer now and whose POSTs wait for the test. */
function serve(initial: LoopState = state(), extra: Record<string, unknown> = {}) {
  const gates: Gate[] = [];
  const posted: string[] = [];
  let failGet = false;
  const response = (ok: boolean, status: number, data: unknown) => ({ ok, status, json: async () => data } as Response);
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (!init?.method || init.method === 'GET') {
      if (url === '/api/memory/loop') {
        if (failGet) return Promise.resolve(response(false, 500, { error: 'the store is busy' }));
        return Promise.resolve(response(true, 200, initial));
      }
      if (url === '/api/memory/graph') {
        if (failGet) return Promise.resolve(response(false, 500, { error: 'the graph store is busy' }));
        return Promise.resolve(response(true, 200, graph));
      }
      return Promise.resolve(response(true, 200, extra[url] ?? {}));
    }
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    posted.push(url);
    return new Promise<Response>((resolve) => {
      gates.push({
        url, body,
        ok: (data = { ok: true }) => { gates.shift(); resolve(response(true, 200, extra[url] ?? data)); },
        fail: (message = 'the store refused it') => { gates.shift(); resolve(response(false, 500, { error: message })); },
      });
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return {
    gates,
    posted,
    failGet() { failGet = true; },
    getMock: fetchMock,
  };
}

/** One held GET for the first load. */
function holdFirstGet() {
  let release: (() => void) | null = null;
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (!init?.method || init.method === 'GET') {
      return new Promise<Response>((resolve) => {
        release = () => resolve({ ok: true, status: 200, json: async () => (url === '/api/memory/graph' ? graph : state()) } as Response);
      });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true }) } as Response);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { release: () => release?.() };
}

async function flush(ms = 0) {
  await act(async () => {
    if (ms) await vi.advanceTimersByTimeAsync(ms);
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('loop feedback', () => {
  it('shows the page skeleton only after a second, never a bare status line first', async () => {
    const held = holdFirstGet();
    const { container } = render(<MemoryLoop pollMs={0} />);
    await flush();
    expect(container.querySelector('.ml-skeleton')).toBeNull();
    await flush(900);
    expect(container.querySelector('.ml-skeleton')).toBeNull();
    await flush(100);
    expect(container.querySelector('.ml-skeleton .ml-flow')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toMatch(/Reading your memory/);
    await act(async () => held.release());
    await flush();
    expect(container.querySelector('.ml-skeleton')).toBeNull();
    expect(screen.getByText(/facts the assistant can recall/)).toBeTruthy();
  });

  it('keeps the page when a poll fails and says it is the previous content', async () => {
    const server = serve();
    render(<MemoryLoop pollMs={8000} />);
    await flush();
    expect(screen.getByText(/facts the assistant can recall/)).toBeTruthy();
    server.failGet();
    await flush(8000);
    expect(screen.getByText(/facts the assistant can recall/)).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/previous content/);
    expect(screen.queryByText('Memory could not be read.')).toBeNull();
  });

  it('shows approve busy on its own button from 100 ms and a result in place', async () => {
    const server = serve();
    render(<MemoryLoop pollMs={0} />);
    await flush();
    const review = screen.getByRole('region', { name: 'Review' });
    const approve = within(review).getAllByRole('button', { name: 'Approve' })[0];
    fireEvent.click(approve);
    expect((approve as HTMLButtonElement).disabled).toBe(true);
    expect(approve.getAttribute('aria-busy')).toBeNull();
    await flush(99);
    expect(approve.getAttribute('aria-busy')).toBeNull();
    await flush(1);
    expect(approve.getAttribute('aria-busy')).toBe('true');
    expect(within(approve).getByText('Saving...')).toBeTruthy();
    fireEvent.click(approve);
    expect(server.gates).toHaveLength(1);
    server.gates[0].ok();
    await flush();
    expect(within(review).getByRole('status').textContent).toMatch(/Saved\./);
  });

  it('reports an approve-all partial result honestly', async () => {
    const server = serve();
    render(<MemoryLoop pollMs={0} />);
    await flush();
    const review = screen.getByRole('region', { name: 'Review' });
    fireEvent.click(within(review).getByRole('button', { name: 'Approve all' }));
    await flush();
    expect(server.gates).toHaveLength(1);
    server.gates[0].ok();
    await flush();
    server.gates[0].ok();
    await flush();
    server.gates[0].fail();
    await flush();
    expect(within(review).getByRole('status').textContent).toMatch(/Approved 2 of 3\. 1 could not be saved\./);
  });

  it('stops a double switch toggle and says a failed setting change in place', async () => {
    const server = serve();
    render(<MemoryLoop pollMs={0} />);
    await flush();
    const settings = screen.getByRole('region', { name: 'Learning settings' });
    const research = within(settings).getByRole('switch', { name: /Research/ });
    fireEvent.click(research);
    fireEvent.click(research);
    expect(server.gates).toHaveLength(1);
    await flush(100);
    expect(research.getAttribute('aria-busy')).toBe('true');
    server.gates[0].fail('the setting is locked');
    await flush();
    expect(research.getAttribute('aria-checked')).toBe('true');
    expect(within(settings).getByRole('alert').textContent).toMatch(/setting is locked/);
  });

  it('shows the observation placeholder after a second, then replaces it with the result', async () => {
    const server = serve(state(), { '/memory/reflect': { ok: true, status: 'ok' } });
    render(<MemoryLoop pollMs={0} />);
    await flush();
    fireEvent.click(screen.getByRole('tab', { name: /Observations/ }));
    const ask = screen.getByRole('button', { name: 'Ask your AI for observations' });
    fireEvent.click(ask);
    await flush(100);
    expect(ask.getAttribute('aria-busy')).toBe('true');
    expect(within(ask).getByText('Asking your AI...')).toBeTruthy();
    await flush(900);
    const panel = screen.getByRole('tabpanel');
    const placeholder = panel.querySelector('.ml-feedback-placeholder');
    expect(placeholder?.classList.contains('ml-row')).toBe(true);
    expect(within(placeholder as HTMLElement).getByRole('status').textContent).toMatch(/Asking your AI for observations/);
    server.gates[0].ok({ ok: true, status: 'ok' });
    await flush();
    expect(screen.getByRole('tabpanel').querySelector('.ml-feedback-placeholder')).toBeNull();
    expect(within(screen.getByRole('tabpanel')).getByRole('status').textContent).toMatch(/waiting in the review queue/);
  });

  it('names the slow wait after ten seconds and says the reader may leave', async () => {
    const server = serve(state(), { '/memory/reflect': { ok: true, status: 'ok' } });
    render(<MemoryLoop pollMs={0} />);
    await flush();
    fireEvent.click(screen.getByRole('tab', { name: /Observations/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Ask your AI for observations' }));
    await flush(10000);
    const panel = screen.getByRole('tabpanel');
    expect(within(panel).getByRole('status').textContent).toMatch(/taking longer than usual/);
    expect(within(panel).getByRole('status').textContent).toMatch(/leave this page/);
    server.gates[0].ok({ ok: true, status: 'ok' });
  });

  it('keeps the typed edit and says a failed save in the row', async () => {
    const server = serve();
    render(<MemoryLoop pollMs={0} />);
    await flush();
    const row = screen.getByText('Acme renews in February.', { selector: '.ml-row-text' }).closest('li') as HTMLElement;
    fireEvent.click(within(row).getByRole('button', { name: 'Edit' }));
    const box = within(row).getByLabelText('Edit fact') as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: 'Acme renews in March.' } });
    fireEvent.click(within(row).getByRole('button', { name: 'Save' }));
    await flush(100);
    expect(within(row).getByRole('button', { name: /Saving/ }).getAttribute('aria-busy')).toBe('true');
    server.gates[0].fail('the store is read only');
    await flush();
    expect(within(row).getByRole('alert').textContent).toMatch(/read only/);
    expect((within(row).getByLabelText('Edit fact') as HTMLTextAreaElement).value).toBe('Acme renews in March.');
  });

  it('keeps the removal dialog open and says a failed confirm in place', async () => {
    const server = serve(state(), {
      '/api/memory/remove/preview': { plan },
      '/api/memory/remove': { removed: { facts: [1], observationsRemoved: [], observationsFlagged: [], observationsUpdated: [], entitiesRemoved: [], sourcesRemoved: [], factsRestored: [] }, undo: { token: 't', expiresTs: NOW + 30 } },
    });
    render(<MemoryLoop pollMs={0} />);
    await flush();
    fireEvent.click(screen.getAllByRole('button', { name: 'Forget…' })[0]);
    await flush();
    server.gates[0].ok({ plan });
    await flush();
    const dialog = screen.getByRole('dialog', { name: 'Acme renews in February.' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove 1 fact' }));
    await flush(100);
    expect(within(dialog).getByRole('button', { name: /Removing/ }).getAttribute('aria-busy')).toBe('true');
    server.gates[0].fail('the file is locked');
    await flush();
    expect(screen.getByRole('dialog', { name: 'Acme renews in February.' })).toBeTruthy();
    expect(within(dialog).getByRole('alert').textContent).toMatch(/file is locked/);
    expect(within(dialog).getByRole('button', { name: 'Remove 1 fact' })).toBeTruthy();
  });

  it('disables Undo while it runs and says a failure in the bar', async () => {
    const server = serve(state(), {
      '/api/memory/remove/preview': { plan },
      '/api/memory/remove': { removed: { facts: [1], observationsRemoved: [], observationsFlagged: [], observationsUpdated: [], entitiesRemoved: [], sourcesRemoved: [], factsRestored: [] }, undo: { token: 't', expiresTs: NOW + 30 } },
      '/api/memory/undo': { ok: true },
    });
    render(<MemoryLoop pollMs={0} />);
    await flush();
    fireEvent.click(screen.getAllByRole('button', { name: 'Forget…' })[0]);
    await flush();
    server.gates[0].ok({ plan });
    await flush();
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove 1 fact' }));
    await flush();
    server.gates[0].ok({
      removed: { facts: [1], observationsRemoved: [], observationsFlagged: [], observationsUpdated: [], entitiesRemoved: [], sourcesRemoved: [], factsRestored: [] },
      undo: { token: 't', expiresTs: NOW + 30 },
    });
    await flush();
    const undo = screen.getByRole('button', { name: 'Undo' });
    fireEvent.click(undo);
    await flush(100);
    expect(undo.getAttribute('aria-busy')).toBe('true');
    expect(within(undo).getByText('Undoing...')).toBeTruthy();
    server.gates[0].fail('the token expired');
    await flush();
    expect(screen.getByRole('alert').textContent).toMatch(/token expired/);
    expect(screen.getByRole('button', { name: 'Undo' })).toBeTruthy();
  });
});

describe('graph feedback', () => {
  it('shows the graph skeleton only after a second', async () => {
    const held = holdFirstGet();
    const { container } = render(<MemoryGraph initialWidth={1000} />);
    await flush();
    expect(container.querySelector('.mg-skeleton')).toBeNull();
    await flush(1000);
    expect(container.querySelector('.mg-skeleton .mg-pipeline')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toMatch(/Reading the graph/);
    await act(async () => held.release());
    await flush();
    expect(container.querySelector('.mg-skeleton')).toBeNull();
    expect(screen.getByText('How this memory was made')).toBeTruthy();
  });

  it('keeps the picture when a refresh fails and says it is the previous picture', async () => {
    const server = serve();
    const { container, rerender } = render(<MemoryGraph initialWidth={1000} reloadKey={0} />);
    await flush();
    expect(container.querySelector('[data-node-id="fact:1"]')).toBeTruthy();
    server.failGet();
    rerender(<MemoryGraph initialWidth={1000} reloadKey={1} />);
    await flush();
    expect(container.querySelector('[data-node-id="fact:1"]')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/previous picture/);
    expect(container.querySelector('.mg-quiet[role="alert"]')).toBeNull();
  });
});
