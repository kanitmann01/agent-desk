import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TrackerSetup from '../dashboard/TrackerSetup';

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

describe('tracker first run', () => {
  it('opens a workbook, shows the disclosure, suggests columns, and confirms', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes('/widgets/settings')) {
        return jsonResponse({ suggest_headers_only: false });
      }
      if (String(url).endsWith('/pick')) {
        return jsonResponse({
          preview: { sheet: 'Data', sheets: ['Data'], headers: ['Region', 'Booked'], rows: [['East', '10']] },
        });
      }
      if (String(url).endsWith('/suggest')) {
        const sent = JSON.parse(String(init?.body || '{}'));
        expect(sent.headersOnly).toBe(false);
        return jsonResponse({
          disclosure: 'This sends the column names and up to 5 rows to the company endpoint. The file path stays on this machine.',
          proposal: { labelColumn: 'Region', valueColumn: 'Booked', aggregate: 'sum' },
          error: '',
        });
      }
      if (String(url).endsWith('/confirm')) {
        const sent = JSON.parse(String(init?.body || '{}'));
        expect(sent.suggested).toBe(true);
        expect(sent.tracking.valueColumn).toBe('Booked');
        return jsonResponse({ step: 'done' });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    const onDone = vi.fn(async () => {});
    render(
      <TrackerSetup
        pluginId="excel-report"
        instanceId="main"
        name="Workbook tracker"
        onDone={onDone}
        onExpired={() => {}}
      />,
    );
    expect(await screen.findByText(/column names and up to 5 rows/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open a workbook' }));
    expect(await screen.findByLabelText('Value column')).toHaveValue('Booked');
    await user.click(screen.getByRole('button', { name: 'Suggest what to track' }));
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(onDone).toHaveBeenCalled();
  });
});
