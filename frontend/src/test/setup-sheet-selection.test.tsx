// T4: the setup sheet's selection surface. Gestures: click toggles, a
// drag across rows sweeps select or deselect (the sweep respects how it
// started), shift-click fills the inclusive range from the last anchor,
// Select all and Clear bound it, and a live count always shows the size.
// The desk's dialog contract (scrim, Escape, focus trap, focus restore,
// error slot) and the confirm payload carrying the ordered zero-based
// data rows are covered through the real TrackerSetup.
import { useState } from 'react';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RowSelectGrid, { type GridPreview } from '../components/RowSelectGrid';
import TrackerCard from '../dashboard/TrackerCard';
import type { PluginCard } from '../types';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// jsdom carries no hit-testing and fireEvent's pointer helper dispatches
// a bare Event, so the modifier gestures dispatch a MouseEvent typed as
// pointerdown (the type React's delegated pointer handlers listen for),
// inside act so the batched re-render lands before the assertion.
async function pointerDown(element: HTMLElement, init: MouseEventInit = {}) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, cancelable: true, button: 0, ...init }));
  });
}

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status < 400,
    status,
    json: async () => body,
  });
}

const PREVIEW: GridPreview = {
  sheet: 'Data',
  headers: ['Region', 'Booked'],
  rows: [
    ['East', '10'],
    ['West', '5'],
    ['North', '7'],
    ['South', '3'],
    ['Coast', '9'],
  ],
};

const TEN_ROWS: GridPreview = {
  sheet: 'Data',
  headers: ['Region', 'Booked'],
  rows: Array.from({ length: 10 }, (_unused, index) => [`Row ${index + 1}`, String(index + 1)]),
};

function Harness({ initial, preview = PREVIEW }: { initial: number[]; preview?: GridPreview }) {
  const [selected, setSelected] = useState(initial);
  return (
    <RowSelectGrid
      preview={preview}
      selected={selected}
      onSelectedChange={setSelected}
    />
  );
}

function rowOf(index: number): HTMLElement {
  const box = screen.getByLabelText(`Track row ${index + 1}`);
  return box.closest('tr') as HTMLElement;
}

async function dragRows(user: ReturnType<typeof userEvent.setup>, path: number[]) {
  const steps: Array<{ keys?: string; target?: HTMLElement }> = [
    { keys: '[MouseLeft>]', target: rowOf(path[0]) },
    ...path.slice(1).map((index) => ({ target: rowOf(index) })),
    { keys: '[/MouseLeft]' },
  ];
  await user.pointer(steps);
}

function expectSelection(indices: number[], preview: GridPreview = PREVIEW) {
  for (let index = 0; index < preview.rows.length; index += 1) {
    const box = screen.getByLabelText(`Track row ${index + 1}`) as HTMLInputElement;
    expect(box.checked, `row ${index + 1}`).toBe(indices.includes(index));
  }
  expect(screen.getByText(`${indices.length}/${preview.rows.length} rows`)).toBeInTheDocument();
}

describe('the setup sheet row selection', () => {
  it('selects a drag sweep across ten rows and the count follows', async () => {
    const user = userEvent.setup();
    render(<Harness initial={[]} preview={TEN_ROWS} />);
    expectSelection([], TEN_ROWS);

    await dragRows(user, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    expectSelection([0, 1, 2, 3, 4, 5, 6, 7, 8, 9], TEN_ROWS);
  });

  it('click toggles one row and dragging the other way deselects the sweep', async () => {
    const user = userEvent.setup();
    render(<Harness initial={[]} />);
    expectSelection([]);

    await user.click(rowOf(2));
    expectSelection([2]);

    await user.click(rowOf(2));
    expectSelection([]);

    cleanup();
    render(<Harness initial={[0, 1, 2, 3, 4]} />);
    // The sweep started on a selected row, so it deselects what it crosses.
    await dragRows(user, [1, 2, 3]);
    expectSelection([0, 4]);
  });

  it('shift-click fills the inclusive range from the last anchor', async () => {
    const user = userEvent.setup();
    render(<Harness initial={[]} />);

    await user.click(rowOf(1));
    expectSelection([1]);

    await pointerDown(rowOf(4), { shiftKey: true });
    expectSelection([1, 2, 3, 4]);
    expect(screen.getByText('4/5 rows')).toBeInTheDocument();

    // A shift-click on a selected row clears its range from the anchor.
    await pointerDown(rowOf(2), { shiftKey: true });
    expectSelection([1]);
  });

  it('select all and clear bound the selection, and checkboxes share the state', async () => {
    const user = userEvent.setup();
    render(<Harness initial={[]} />);

    await user.click(screen.getByRole('button', { name: 'Select all' }));
    expectSelection([0, 1, 2, 3, 4]);

    await user.click(screen.getByLabelText('Track row 3'));
    expectSelection([0, 1, 3, 4]);

    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expectSelection([]);

    await user.click(screen.getByLabelText('Track row 2'));
    expectSelection([1]);
  });

  it('carries the gesture selection through the confirm payload and honors the dialog contract', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.includes('/widgets/settings')) {
        return jsonResponse({ suggest_headers_only: false });
      }
      if (url.endsWith('/pick')) {
        return jsonResponse({
          preview: { sheet: 'Data', headers: ['Region', 'Booked'], rows: PREVIEW.rows },
        });
      }
      if (url.endsWith('/confirm')) {
        return jsonResponse({ step: 'done' });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    const onDone = vi.fn(async () => {});
    render(<TrackerCard card={setupCard()} onRefetch={onDone} onExpired={() => {}} />);

    const opener = screen.getByRole('button', { name: 'Set up' });
    await user.click(opener);
    const dialog = screen.getByRole('dialog', { name: 'Set up this tracker' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Close dialog' })).toHaveFocus());

    await user.click(within(dialog).getByRole('button', { name: 'Open a workbook' }));
    expect(await screen.findByRole('columnheader', { name: 'Booked' })).toBeInTheDocument();

    // Gestures and checkboxes share one state: clear, tick two rows, then
    // sweep two more, and the payload must carry all four in order.
    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.getByText('0/5 rows')).toBeInTheDocument();
    await user.click(screen.getByLabelText('Track row 1'));
    await user.click(screen.getByLabelText('Track row 3'));
    await dragRows(user, [3, 4]);
    expect(screen.getByText('4/5 rows')).toBeInTheDocument();

    // The Tab trap: shift-tab from the first focusable wraps to the last
    // enabled control (Continue waits on a column choice).
    within(dialog).getByRole('button', { name: 'Close dialog' }).focus();
    await user.tab({ shift: true });
    expect(within(dialog).getByLabelText('Aggregate')).toHaveFocus();

    await user.click(within(dialog).getByRole('button', { name: 'Booked' }));
    await user.click(within(dialog).getByRole('radio', { name: 'Row label' }));
    await user.click(within(dialog).getByRole('button', { name: 'Region' }));
    await user.click(within(dialog).getByRole('button', { name: 'Continue' }));
    const name = within(dialog).getByLabelText('Instance name');
    await user.clear(name);
    await user.type(name, 'Q4 bookings');
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());

    const confirmCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/confirm'));
    const body = JSON.parse(String((confirmCall?.[1] as RequestInit).body));
    expect(body.tracking.rows).toEqual([0, 2, 3, 4]);

    // Escape closes and focus returns to the opener.
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
  });

  it('a pointer-down on the scrim closes the sheet and a failed confirm surfaces the error slot', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.includes('/widgets/settings')) {
        return jsonResponse({ suggest_headers_only: false });
      }
      if (url.endsWith('/pick')) {
        return jsonResponse({
          preview: { sheet: 'Data', headers: ['Region', 'Booked'], rows: PREVIEW.rows },
        });
      }
      if (url.endsWith('/confirm')) {
        return jsonResponse({ error: 'config:not-granted', message: 'That file moved. Open it again.' }, 400);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    const onDone = vi.fn(async () => {});
    render(<TrackerCard card={setupCard()} onRefetch={onDone} onExpired={() => {}} />);

    await user.click(screen.getByRole('button', { name: 'Set up' }));
    await user.click(screen.getByRole('button', { name: 'Open a workbook' }));
    expect(await screen.findByRole('columnheader', { name: 'Booked' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Booked' }));
    await user.click(screen.getByRole('radio', { name: 'Row label' }));
    await user.click(screen.getByRole('button', { name: 'Region' }));
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That file moved. Open it again.');
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // The scrim itself is the close affordance; a drag release never hits it.
    await pointerDown(screen.getByTestId('setup-scrim'));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Set up' })).toHaveFocus();
    expect(onDone).not.toHaveBeenCalled();
  });
});

function setupCard(): PluginCard {
  return {
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
}
