import { cleanup, render, screen } from '@testing-library/react';
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
});
