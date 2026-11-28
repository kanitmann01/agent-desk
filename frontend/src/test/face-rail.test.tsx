// Ticket 02: the rail brand row, command-bar gaze, and user-driven waits.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import CommandBar from '../components/CommandBar';
import Dashboard from '../dashboard/Dashboard';
import PluginCardView from '../dashboard/PluginCardView';
import Rail from '../dashboard/Rail';
import { FaceProvider, useFaceState, type ResolvedFaceState } from '../face/FaceProvider';
import FaceSlot from '../face/FaceSlot';
import { DONE_DURATION_MS } from '../face/moods';
import { AGENT_NAME } from '../face/name';
import type { DashboardData, PluginCard } from '../types';

const here = dirname(fileURLToPath(import.meta.url));
const indexCss = readFileSync(resolve(here, '..', 'index.css'), 'utf8');

const NOOP = () => {};
const NOOP_REFETCH = async () => {};

const BASE_DATA: DashboardData = {
  version: '0.0.0-test',
  flags: { excelEnabled: true, calendarEnabled: true, endpointEnabled: true },
  sources: {
    connected: 1,
    total: 3,
    items: [{ id: 'research-endpoint', status: 'connected', detail: 'AI connected.' }],
  },
  sales: { enabled: true, mode: 'unconfigured', status: null },
  commitments: { enabled: true, mode: 'unavailable', status: null },
  research: { enabled: true, lastAnsweredTs: null },
  inbox: { waiting: 0 },
  skills: [{ id: 1, name: 'Monday numbers', description: 'Summarize the sheet' }],
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

const DIGEST_CARD: PluginCard = {
  id: 'outlook-digest',
  title: 'Outlook Brief',
  version: '0.3.0',
  pilot: false,
  state: 'enabled',
  freshness: 'fresh',
  cause: '',
  payload: {
    elements: [{ kind: 'text', label: 'Reading', text: 'Q4 forecast is waiting on you.' }],
    insight: {
      status: 'ok',
      source: 'local',
      note: '',
      press: {
        label: 'Draft the reply',
        route: '/api/insight/draft',
        kind: 'reply-draft',
        thread: { subject: 'Q4 forecast', sender: 'Dana Whitfield' },
      },
      blocks: [],
    },
  },
};

const STALE_PLUGIN_CARD: PluginCard = {
  id: 'crm-sync',
  title: 'CRM Sync',
  version: '0.2.0',
  pilot: false,
  state: 'enabled',
  freshness: 'attention',
  cause: 'data source has not run',
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status < 400,
    status,
    json: async () => body,
  } as Response;
}

function StateObserver({ onState }: { onState: (state: ResolvedFaceState | null) => void }) {
  const state = useFaceState();
  onState(state);
  return null;
}

function getRailFace(): HTMLElement | null {
  return document.querySelector('[data-face-slot="rail"] .face-box');
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  localStorage.removeItem('agentdesk.railCollapsed');
});

describe('rail brand placement and collapsed layout', () => {
  it(`places FaceSlot inside .brand before ${AGENT_NAME} and excludes .phone-bar`, () => {
    render(
      <FaceProvider trackPointer={false}>
        <Rail inboxWaiting={0} />
      </FaceProvider>,
    );

    const brand = document.querySelector('.rail .brand') as HTMLElement;
    expect(brand).not.toBeNull();
    const slot = brand.querySelector('[data-face-slot="rail"]') as HTMLElement;
    const wordmark = brand.querySelector('.brand-name') as HTMLElement;
    expect(slot).not.toBeNull();
    expect(wordmark).toHaveTextContent(AGENT_NAME);
    expect(brand.firstElementChild).toBe(slot);
    expect(slot.compareDocumentPosition(wordmark) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);

    const phoneBar = document.querySelector('.rail .phone-bar') as HTMLElement;
    expect(phoneBar).not.toBeNull();
    expect(phoneBar.querySelector('[data-face-slot]')).toBeNull();
    expect(phoneBar.querySelector('.face-box')).toBeNull();
  });

  it('keeps the rail face visible when collapsed and adjusts .rail-collapsed .brand padding', async () => {
    const user = userEvent.setup();
    render(
      <FaceProvider trackPointer={false}>
        <div className="app">
          <Rail inboxWaiting={0} />
        </div>
      </FaceProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'Collapse navigation' }));
    expect(document.querySelector('.app')).toHaveClass('rail-collapsed');
    expect(document.querySelector('.brand [data-face-slot="rail"] .face-box')).toBeInTheDocument();

    // Verify desktop collapsed rule centers the 32px face inside the 68px rail without clipping.
    expect(indexCss).toContain('.rail-collapsed .brand{justify-content:center;padding:2px 0 18px;gap:0}');
    expect(indexCss).toContain('.rail-collapsed .brand b,.rail-collapsed .brand-name{display:none}');
  });

  it('wraps App in FaceProvider so the dashboard renders the rail face on load', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(BASE_DATA)));
    render(<App />);
    await screen.findByRole('navigation', { name: 'Main' });
    const face = getRailFace();
    expect(face).toBeInTheDocument();
    expect(face).toHaveAttribute('data-mood', 'idle');
  });
});

describe('CommandBar listening and gaze tracking', () => {
  it('shifts to listening with lookTarget on focus, updates on input/resize, and clears on blur and unmount', () => {
    const stateRef: { current: ResolvedFaceState | null } = { current: null };
    let rect = { left: 100, top: 200, width: 400, height: 40 };

    const { rerender, unmount } = render(
      <FaceProvider trackPointer={false}>
        <FaceSlot slot="rail" />
        <StateObserver onState={(s) => { stateRef.current = s; }} />
        <CommandBar busy={false} onAsk={vi.fn(async () => true)} />
      </FaceProvider>,
    );

    const field = screen.getByLabelText('Research question') as HTMLTextAreaElement;
    vi.spyOn(field, 'getBoundingClientRect').mockImplementation(() => ({
      ...rect,
      right: rect.left + rect.width,
      bottom: rect.top + rect.height,
      x: rect.left,
      y: rect.top,
      toJSON: () => ({}),
    }));

    expect(getRailFace()).toHaveAttribute('data-mood', 'idle');
    expect(stateRef.current?.lookTarget).toBeNull();

    fireEvent.focus(field);
    expect(getRailFace()).toHaveAttribute('data-mood', 'listening');
    expect(getRailFace()).toHaveAttribute('title', `${AGENT_NAME}: Listening to your question`);
    expect(stateRef.current?.lookTarget).toEqual({ x: 300, y: 220 });

    // Input growth shifts the vertical center.
    rect = { left: 100, top: 200, width: 400, height: 80 };
    fireEvent.change(field, { target: { value: 'Line 1\nLine 2' } });
    expect(stateRef.current?.lookTarget).toEqual({ x: 300, y: 240 });

    // Viewport resize updates the target center.
    rect = { left: 140, top: 220, width: 420, height: 80 };
    fireEvent(window, new Event('resize'));
    expect(stateRef.current?.lookTarget).toEqual({ x: 350, y: 260 });

    // Blur clears listening and lookTarget.
    fireEvent.blur(field);
    expect(getRailFace()).toHaveAttribute('data-mood', 'idle');
    expect(stateRef.current?.lookTarget).toBeNull();

    // Unmount while focused also clears lookTarget and listening.
    fireEvent.focus(field);
    expect(getRailFace()).toHaveAttribute('data-mood', 'listening');
    expect(stateRef.current?.lookTarget).toEqual({ x: 350, y: 260 });
    rerender(
      <FaceProvider trackPointer={false}>
        <FaceSlot slot="rail" />
        <StateObserver onState={(s) => { stateRef.current = s; }} />
      </FaceProvider>,
    );
    expect(getRailFace()).toHaveAttribute('data-mood', 'idle');
    expect(stateRef.current?.lookTarget).toBeNull();
    unmount();
  });

  it('stays safe when rendered standalone without FaceProvider', () => {
    render(<CommandBar busy={false} onAsk={vi.fn(async () => true)} />);
    const field = screen.getByLabelText('Research question');
    fireEvent.focus(field);
    fireEvent.change(field, { target: { value: 'Hello' } });
    fireEvent.blur(field);
    expect(field).toHaveValue('Hello');
  });
});

describe('Dashboard waits, inbox waiting, poll errors, and priority', () => {
  it('drives thinking -> done -> waiting across ask() and respects priority over listening', async () => {
    vi.useFakeTimers();
    const gate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(() => gate.promise));

    const waitingData: DashboardData = { ...BASE_DATA, inbox: { waiting: 3 } };
    render(
      <FaceProvider trackPointer={false}>
        <Dashboard data={waitingData} onRefetch={NOOP_REFETCH} onExpired={NOOP} />
      </FaceProvider>,
    );

    const face = getRailFace()!;
    expect(face).toHaveAttribute('data-mood', 'waiting');
    expect(face).toHaveAttribute('title', `${AGENT_NAME}: 3 waiting in Inbox`);

    // Focusing CommandBar does not override waiting (waiting > listening).
    const field = screen.getByLabelText('Research question');
    fireEvent.focus(field);
    expect(face).toHaveAttribute('data-mood', 'waiting');

    // Starting ask() promotes request thinking above waiting.
    fireEvent.change(field, { target: { value: 'Who booked Q4?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Research' }));
    expect(face).toHaveAttribute('data-mood', 'thinking');

    await act(async () => {
      gate.resolve(jsonResponse({ status: 'ok', summary: 'Meridian booked Q4.', sources: [] }));
    });
    expect(face).toHaveAttribute('data-mood', 'done');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(DONE_DURATION_MS + 20);
    });
    expect(face).toHaveAttribute('data-mood', 'waiting');
  });

  it('drives blocked while answerError is shown after a degraded or failed ask', async () => {
    const gate = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(() => gate.promise));

    render(
      <FaceProvider trackPointer={false}>
        <Dashboard data={BASE_DATA} onRefetch={NOOP_REFETCH} onExpired={NOOP} />
      </FaceProvider>,
    );

    const field = screen.getByLabelText('Research question');
    fireEvent.change(field, { target: { value: 'What failed?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Research' }));
    expect(getRailFace()).toHaveAttribute('data-mood', 'thinking');

    await act(async () => {
      gate.resolve(jsonResponse({ status: 'degraded', cause: 'No AI key is saved.' }));
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'blocked');
  });

  it('drives thinking -> done for runSkill success and blocked for runSkill failure', async () => {
    vi.useFakeTimers();
    const okGate = deferred<Response>();
    const failGate = deferred<Response>();
    let call = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: RequestInfo | URL) => {
        if (String(url) === '/skills/1/run') {
          call += 1;
          return call === 1 ? okGate.promise : failGate.promise;
        }
        return jsonResponse({});
      }),
    );

    render(
      <FaceProvider trackPointer={false}>
        <Dashboard data={BASE_DATA} onRefetch={NOOP_REFETCH} onExpired={NOOP} />
      </FaceProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Run Monday numbers' }));
    expect(getRailFace()).toHaveAttribute('data-mood', 'thinking');

    await act(async () => {
      okGate.resolve(jsonResponse({ status: 'ok', summary: 'Monday numbers ready.' }));
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'done');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(DONE_DURATION_MS + 20);
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'idle');

    // Second run fails -> blocked.
    fireEvent.click(screen.getByRole('button', { name: 'Run Monday numbers' }));
    expect(getRailFace()).toHaveAttribute('data-mood', 'thinking');

    await act(async () => {
      failGate.resolve(jsonResponse({ status: 'error', cause: 'Workbook missing.' }));
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'blocked');
  });

  it('reports blocked when pollNote is non-empty and clears when poll recovers', () => {
    const waitingData: DashboardData = { ...BASE_DATA, inbox: { waiting: 2 } };
    const { rerender } = render(
      <FaceProvider trackPointer={false}>
        <Dashboard
          data={waitingData}
          onRefetch={NOOP_REFETCH}
          onExpired={NOOP}
          pollNote="The desk could not be reached just now."
        />
      </FaceProvider>,
    );

    // blocked outranks inbox waiting.
    expect(getRailFace()).toHaveAttribute('data-mood', 'blocked');
    expect(getRailFace()).toHaveAttribute('title', `${AGENT_NAME}: The desk could not be reached`);

    rerender(
      <FaceProvider trackPointer={false}>
        <Dashboard data={waitingData} onRefetch={NOOP_REFETCH} onExpired={NOOP} pollNote="" />
      </FaceProvider>,
    );
    expect(getRailFace()).toHaveAttribute('data-mood', 'waiting');
  });
});

describe('PluginCardView PressOffer and retest face transitions', () => {
  it('drives thinking -> done on PressOffer draft/stage and blocked on refusal', async () => {
    vi.useFakeTimers();
    const draftGate = deferred<Response>();
    const stageGate = deferred<Response>();
    const refusalGate = deferred<Response>();
    let step = 0;

    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        step += 1;
        if (step === 1) return draftGate.promise;
        if (step === 2) return stageGate.promise;
        return refusalGate.promise;
      }),
    );

    render(
      <FaceProvider trackPointer={false}>
        <FaceSlot slot="rail" />
        <PluginCardView card={DIGEST_CARD} onRefetch={NOOP_REFETCH} onExpired={NOOP} />
      </FaceProvider>,
    );

    expect(getRailFace()).toHaveAttribute('data-mood', 'idle');

    // Draft reply -> thinking -> done.
    fireEvent.click(screen.getByRole('button', { name: 'Draft the reply' }));
    expect(getRailFace()).toHaveAttribute('data-mood', 'thinking');

    await act(async () => {
      draftGate.resolve(
        jsonResponse({
          status: 'draft',
          text: 'Hi Dana, looking into it.',
          disclosure: ['Sends subject.'],
          note: '',
        }),
      );
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'done');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(DONE_DURATION_MS + 20);
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'idle');

    // Stage reply -> thinking -> done.
    fireEvent.click(screen.getByRole('button', { name: 'Stage as a reply card' }));
    expect(getRailFace()).toHaveAttribute('data-mood', 'thinking');

    await act(async () => {
      stageGate.resolve(jsonResponse({ staged: true, cardId: 'card-42' }));
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'done');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(DONE_DURATION_MS + 20);
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'idle');

    // Refusal on next draft -> blocked.
    fireEvent.click(screen.getByRole('button', { name: 'Draft the reply' }));
    expect(getRailFace()).toHaveAttribute('data-mood', 'thinking');

    await act(async () => {
      refusalGate.resolve(jsonResponse({ error: 'Model calls are off.' }, 409));
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'blocked');
  });

  it('drives reading -> done on retest success and blocked on retest failure', async () => {
    vi.useFakeTimers();
    const okGate = deferred<Response>();
    const failGate = deferred<Response>();
    let call = 0;

    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        call += 1;
        return call === 1 ? okGate.promise : failGate.promise;
      }),
    );

    render(
      <FaceProvider trackPointer={false}>
        <FaceSlot slot="rail" />
        <PluginCardView card={STALE_PLUGIN_CARD} onRefetch={NOOP_REFETCH} onExpired={NOOP} />
      </FaceProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Widget options, CRM Sync' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Re-test now' }));
    expect(getRailFace()).toHaveAttribute('data-mood', 'reading');

    await act(async () => {
      okGate.resolve(jsonResponse({ status: 'ok' }));
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'done');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(DONE_DURATION_MS + 20);
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'idle');

    // Second retest fails -> blocked.
    fireEvent.click(screen.getByRole('button', { name: 'Widget options, CRM Sync' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Re-test now' }));
    expect(getRailFace()).toHaveAttribute('data-mood', 'reading');

    await act(async () => {
      failGate.resolve(jsonResponse({ error: 'Failed' }, 500));
    });
    expect(getRailFace()).toHaveAttribute('data-mood', 'blocked');
  });
});
