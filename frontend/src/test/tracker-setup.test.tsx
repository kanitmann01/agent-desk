import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
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

const setupCard: PluginCard = {
  id: 'excel-report',
  title: 'Workbook tracker',
  version: '0.1.0',
  pilot: false,
  state: 'enabled',
  freshness: 'setup',
  cause: '',
  payload: {
    elements: [],
    setup: { pluginId: 'excel-report', instanceId: 'main', name: 'Workbook tracker', step: 'source' },
  },
};

describe('tracker setup sheet', () => {
  it('opens a workbook, highlights a suggestion, and names the instance', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes('/widgets/settings')) {
        return jsonResponse({ suggest_headers_only: false });
      }
      if (String(url).endsWith('/pick')) {
        return jsonResponse({
          preview: {
            sheet: 'Data',
            headers: ['Region', 'Booked'],
            rows: [['East', '10'], ['West', '5']],
          },
        });
      }
      if (String(url).endsWith('/suggest')) {
        return jsonResponse({
          disclosure: 'This sends the column names and up to 5 rows to the company endpoint. The file path stays on this machine.',
          proposal: {
            labelColumn: 'Region',
            valueColumn: 'Booked',
            aggregate: 'sum',
            rows: [0, 1],
            reason: 'Booked looks like the amount; Region groups rows.',
            source: 'heuristic',
          },
        });
      }
      if (String(url).endsWith('/confirm')) {
        return jsonResponse({ step: 'done' });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    const onDone = vi.fn(async () => {});
    render(<TrackerCard card={setupCard} onRefetch={onDone} onExpired={() => {}} />);
    expect(screen.queryByText('PILOT')).toBeNull();
    expect(screen.queryByText(/plugin v/)).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Set up' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open a workbook' }));
    expect(await screen.findByRole('columnheader', { name: 'Booked' })).toBeInTheDocument();
    expect(screen.getByText(/Sends the headers Region, Booked and 2 rows/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Suggest what to track' }));
    expect(await screen.findByText(/Suggested on this machine/)).toBeInTheDocument();
    expect(screen.getByText(/Booked looks like the amount/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Accept' }));
    const name = screen.getByLabelText('Instance name');
    await user.clear(name);
    await user.type(name, 'Q4 bookings');
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(onDone).toHaveBeenCalled();
  });

  it('an outside-workspace refusal offers the honest accept and retries the confirm', async () => {
    const user = userEvent.setup();
    const outsideCalls: string[] = [];
    let confirmCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      const target = String(url);
      if (target.includes('/widgets/settings')) {
        return jsonResponse({ suggest_headers_only: false });
      }
      if (target.endsWith('/pick')) {
        return jsonResponse({
          preview: {
            sheet: 'Data',
            headers: ['Region', 'Booked'],
            rows: [['East', '10'], ['West', '5']],
          },
        });
      }
      if (target.endsWith('/suggest')) {
        return jsonResponse({
          disclosure: 'This sends the column names and up to 5 rows to the company endpoint. The file path stays on this machine.',
          proposal: {
            labelColumn: 'Region',
            valueColumn: 'Booked',
            aggregate: 'sum',
            rows: [0, 1],
            reason: 'Booked looks like the amount; Region groups rows.',
            source: 'heuristic',
          },
        });
      }
      if (target.endsWith('/outside')) {
        outsideCalls.push(target);
        return jsonResponse({ outsideAccepted: true });
      }
      if (target.endsWith('/confirm')) {
        confirmCalls += 1;
        if (confirmCalls === 1) {
          return jsonResponse({ error: 'config:outside-workspace',
                                message: 'That file is outside the workspace. Accept it before confirming.' }, 400);
        }
        return jsonResponse({ step: 'done' });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    const onDone = vi.fn(async () => {});
    render(<TrackerCard card={setupCard} onRefetch={onDone} onExpired={() => {}} />);

    await user.click(screen.getByRole('button', { name: 'Set up' }));
    await user.click(screen.getByRole('button', { name: 'Open a workbook' }));
    expect(await screen.findByRole('columnheader', { name: 'Booked' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Suggest what to track' }));
    await user.click(await screen.findByRole('button', { name: 'Accept' }));
    const name = screen.getByLabelText('Instance name');
    await user.clear(name);
    await user.type(name, 'Q4 bookings');
    await user.click(screen.getByRole('button', { name: 'Confirm' }));

    // The refusal becomes the honest inline choice, not a dead end.
    expect(await screen.findByText(/outside the workspace folder/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Use it anyway' }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(confirmCalls).toBe(2);
    expect(outsideCalls.length).toBe(1);
    expect(outsideCalls[0]).toContain('/instances/main/outside');
  });
  it('opens the sheet from an amber card whose workbook went missing (no setup step on the card)', async () => {
    const user = userEvent.setup();
    const pickCalls: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes('/widgets/settings')) {
        return jsonResponse({ suggest_headers_only: false });
      }
      if (String(url).endsWith('/pick')) {
        pickCalls.push(String(url));
        return jsonResponse({
          preview: { sheet: 'Data', headers: ['Region', 'Booked'], rows: [['East', '10']] },
        });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    // A confirmed tracker whose file moved: the server sends the cause
    // and no payload at all, so the card has no setup step to render.
    const card: PluginCard = {
      id: 'excel-report~main',
      title: 'Q4 bookings',
      version: '0.1.0',
      pilot: false,
      state: 'enabled',
      freshness: 'attention',
      cause: 'no workbook matches reports/*.xlsx',
      pluginId: 'excel-report',
      instanceId: 'main',
      payload: null,
    };
    render(<TrackerCard card={card} onRefetch={async () => {}} onExpired={() => {}} />);
    expect(screen.getByText('no workbook matches reports/*.xlsx')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Set up' }));

    expect(screen.getByRole('dialog', { name: 'Set up this tracker' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open a workbook' }));
    await waitFor(() => expect(pickCalls.length).toBe(1));
    expect(pickCalls[0]).toContain('/api/plugins/excel-report/instances/main/pick');
  });
});
