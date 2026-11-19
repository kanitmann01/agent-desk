// Ticket 06: the press in the SPA. The button is the card's own offer, the
// answer lands in place, the disclosure is drawn above any stage action, and
// a refusal is the desk's sentence — never a status code dressed as one.
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import PluginCardView from '../dashboard/PluginCardView';
import TrackerCard from '../dashboard/TrackerCard';
import type { PluginCard } from '../types';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status < 400,
    status,
    json: async () => body,
  });
}

interface PressCall {
  url: string;
  body: Record<string, unknown>;
}

const TRACKER = {
  name: 'Q4 bookings',
  value: '12,400',
  unit: 'GBP',
  delta: '-8%',
  direction: 'down',
  points: [12, 11, 10, 9],
  file: 'reports/q4-bookings.xlsx',
};

const EXPLAIN_PRESS = {
  label: 'Explain this range',
  route: '/api/insight/draft',
  kind: 'explain-range' as const,
  text: 'Booked is 18 rows behind last month.',
};

const EXPLANATION = {
  status: 'draft',
  text: 'West booked nothing in weeks 8 and 9, which is where the eight points went.',
  source: 'model',
  disclosure: [
    'Sends: the one sentence this card already shows, with its column names, its numbers and the chart the desk chose.',
    'Does not send: the workbook, its rows, the calendar, or any memory.',
  ],
  note: '',
};

const workbookCard: PluginCard = {
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
    elements: [],
    insight: {
      status: 'ok',
      source: 'local',
      note: '',
      press: EXPLAIN_PRESS,
      receipts: { preferences: [], inputs: ['rows'] },
    },
  },
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
    elements: [
      { kind: 'text', label: 'Reading', text: 'Q4 forecast is waiting on you and touches your focus topics.' },
    ],
    insight: {
      status: 'ok',
      source: 'local',
      note: '',
      preferences: ['replyTone'],
      press: {
        label: 'Draft the reply',
        route: '/api/insight/draft',
        kind: 'reply-draft',
        subject: 'Q4 forecast',
        sender: 'Dana Whitfield',
      },
      receipts: { preferences: ['replyTone'], inputs: ['memory'], counts: { memory: 1 } },
    },
  },
};

const DRAFT = {
  status: 'draft',
  text: 'Hi Dana, thanks for the Q4 forecast; I will look at it today.',
  source: 'template',
  disclosure: [
    "Sends: the thread's subject, who it is from, and its last line.",
    'Does not send: the rest of the thread, the workbook, the calendar, or any memory.',
  ],
  note: "A skeleton from the thread's subject and greeting; no message body was read.",
  thread: { id: 't-9', to: 'dana@example.com', subject: 'Q4 forecast' },
};

const STAGED = {
  ...DRAFT,
  text: '',
  disclosure: [],
  note: '',
  staged: true,
  cardId: 'card-42',
};

describe('the press on a card', () => {
  it('explains the range in place, with the press disabled until the desk answers', async () => {
    const user = userEvent.setup();
    const calls: PressCall[] = [];
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: { body?: string }) => {
        calls.push({ url: String(url), body: JSON.parse(init?.body ?? '{}') as Record<string, unknown> });
        await gate;
        return jsonResponse(EXPLANATION);
      }),
    );
    render(<TrackerCard card={workbookCard} onRefetch={async () => {}} onExpired={() => {}} />);

    expect(screen.queryByRole('list', { name: 'What this press sends' })).toBeNull();
    const press = screen.getByRole('button', { name: 'Explain this range' });
    await user.click(press);
    await waitFor(() => expect(press).toBeDisabled());
    await act(async () => {
      release();
    });

    expect(await screen.findByText(EXPLANATION.text)).toBeInTheDocument();
    expect(screen.getByText(EXPLANATION.disclosure[0])).toBeInTheDocument();
    expect(screen.getByText(EXPLANATION.disclosure[1])).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Stage as a reply card' })).toBeNull();
    await waitFor(() => expect(press).toBeEnabled());
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe('/api/insight/draft');
    expect(calls[0].body).toEqual({ kind: 'explain-range', text: 'Booked is 18 rows behind last month.' });
  });

  it('drafts the reply, offers the stage under the disclosure, then names the card it became', async () => {
    const user = userEvent.setup();
    const calls: PressCall[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: { body?: string }) => {
        const body = JSON.parse(init?.body ?? '{}') as Record<string, unknown>;
        calls.push({ url: String(url), body });
        return body.stage === true ? jsonResponse(STAGED) : jsonResponse(DRAFT);
      }),
    );
    const onRefetch = vi.fn(async () => {});
    render(<PluginCardView card={DIGEST_CARD} onRefetch={onRefetch} onExpired={() => {}} />);

    await user.click(screen.getByRole('button', { name: 'Draft the reply' }));
    expect(await screen.findByText(DRAFT.text)).toBeInTheDocument();
    const disclosure = screen.getByRole('list', { name: 'What this press sends' });
    const stage = screen.getByRole('button', { name: 'Stage as a reply card' });
    expect(screen.getByText(DRAFT.note)).toBeInTheDocument();
    // The disclosure comes before the stage action in the document.
    expect(disclosure.compareDocumentPosition(stage) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);

    await user.click(stage);
    expect(
      await screen.findByText('Staged as a card: card-42. Open the inbox to accept or edit it.'),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(2);
    expect(calls[1].body).toEqual({
      kind: 'reply-draft',
      subject: 'Q4 forecast',
      sender: 'Dana Whitfield',
      stage: true,
    });
    // Nothing was re-drafted: the draft the person read is still there.
    expect(screen.getByText(DRAFT.text)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Stage as a reply card' })).toBeNull();
    expect(onRefetch).toHaveBeenCalled();
  });

  it('says a card already existed instead of staging the same reply twice', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: { body?: string }) => {
        const body = JSON.parse(init?.body ?? '{}') as Record<string, unknown>;
        return body.stage === true
          ? jsonResponse({ ...STAGED, staged: false, cardId: 'card-7' })
          : jsonResponse(DRAFT);
      }),
    );
    render(<PluginCardView card={DIGEST_CARD} onRefetch={async () => {}} onExpired={() => {}} />);

    await user.click(screen.getByRole('button', { name: 'Draft the reply' }));
    await screen.findByText(DRAFT.text);
    await user.click(screen.getByRole('button', { name: 'Stage as a reply card' }));

    expect(
      await screen.findByText(
        'This reply was already staged as a card: card-7. Open the inbox to accept or edit it.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it("shows the desk's sentence when model calls are off", async () => {
    const user = userEvent.setup();
    const modelOff =
      'Nothing was explained: model calls are off on this desk, so there is no model to explain with. Turn the model on in Settings, then ask again.';
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ error: modelOff, code: 'insight:model-off' }, 409)));
    render(<TrackerCard card={workbookCard} onRefetch={async () => {}} onExpired={() => {}} />);

    const press = screen.getByRole('button', { name: 'Explain this range' });
    await user.click(press);

    expect(await screen.findByRole('alert')).toHaveTextContent(modelOff);
    expect(screen.queryByRole('button', { name: 'Stage as a reply card' })).toBeNull();
    expect(screen.queryByRole('list', { name: 'What this press sends' })).toBeNull();
    await waitFor(() => expect(press).toBeEnabled());
  });

  it('shows the refusal when the thread is gone, and offers nothing else', async () => {
    const user = userEvent.setup();
    const noThread = 'That thread is no longer in the inbox, so there is nothing to draft into.';
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ error: noThread, code: 'insight:no-thread' }, 404)),
    );
    render(<PluginCardView card={DIGEST_CARD} onRefetch={async () => {}} onExpired={() => {}} />);

    await user.click(screen.getByRole('button', { name: 'Draft the reply' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(noThread);
    expect(screen.queryByRole('button', { name: 'Stage as a reply card' })).toBeNull();
    expect(screen.queryByText(/could not answer|went wrong/i)).toBeNull();
  });
});

describe('the press on a nested-thread card (ticket 07)', () => {
  it('posts the thread the payload nests, as the digest family emits it', async () => {
    const user = userEvent.setup();
    const calls: PressCall[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: { body?: string }) => {
        calls.push({ url, body: JSON.parse(init?.body ?? '{}') as Record<string, unknown> });
        return jsonResponse(DRAFT);
      }),
    );
    // The backend nests the facts under "thread"; the SPA must not drop them.
    const nestedCard: PluginCard = {
      ...DIGEST_CARD,
      payload: {
        ...DIGEST_CARD.payload!,
        insight: {
          ...DIGEST_CARD.payload!.insight!,
          press: {
            label: 'Draft the reply',
            route: '/api/insight/draft',
            kind: 'reply-draft',
            thread: { subject: 'Q4 plan', sender: 'sender@example.com' },
          },
        },
      },
    };
    render(<PluginCardView card={nestedCard} onRefetch={async () => {}} onExpired={() => {}} />);

    await user.click(screen.getByRole('button', { name: 'Draft the reply' }));
    expect(await screen.findByText(DRAFT.text)).toBeInTheDocument();
    expect(calls).toHaveLength(1);
    const body = calls[0].body;
    const namesThread =
      (body.thread as { subject?: string } | undefined)?.subject === 'Q4 plan' ||
      body.subject === 'Q4 plan';
    expect(namesThread).toBe(true);
  });
});
