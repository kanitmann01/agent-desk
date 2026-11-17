// The manage view's instance setup (T5, finished in T6): a config-backed
// plugin lists its instances with Set up and Edit; the sheet is the
// desk's shared flow (ModalSheet shell + RowSelectGrid preview), walking
// name -> open workbook -> columns and rows -> confirm carrying
// tracking.rows against the same endpoints the dashboard card drives.
// A plain plugin shows no setup entry; an alias never opens a second
// config surface; a refused action surfaces the server's error, never a
// silent no-op.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { detail, detailResponse, installed } from './marketplace-fixtures';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

const CONFIG_INSTANCE = {
  schemaVersion: 1,
  instanceId: 'pipeline',
  name: 'Pipeline',
  source: {
    kind: 'workbook',
    path: '/workspace/reports/q4.xlsx',
    sheet: null,
    headerRow: 1,
    range: null,
  },
  tracking: { labelColumn: 'Region', valueColumn: 'Booked', aggregate: 'sum' },
  confirmedAt: '2026-11-17T10:00:00',
  suggested: false,
};

const UNCONFIGURED_INSTANCE = {
  schemaVersion: 1,
  instanceId: 'board-pack',
  name: 'Board pack',
  source: null,
  tracking: { good: 'up' },
  confirmedAt: null,
  suggested: false,
};

const PREVIEW = {
  headers: ['Region', 'Booked'],
  // The server stringifies every cell (preview_table), so the stub does too.
  rows: [['East', '10'], ['West', '5']],
  sheet: 'Data',
};

interface ListOverrides {
  pluginId?: string;
  configBacked?: boolean;
  aliasOf?: string | null;
  setupPluginId?: string;
  setupPluginName?: string;
  instances?: unknown[];
}

function listing(overrides: ListOverrides = {}) {
  return {
    pluginId: 'qbr-pack',
    configBacked: true,
    aliasOf: null,
    setupPluginId: 'qbr-pack',
    setupPluginName: 'QBR pack',
    instances: [CONFIG_INSTANCE, UNCONFIGURED_INSTANCE],
    ...overrides,
  };
}

interface StubOptions {
  pick?: { status: number; body: unknown };
  confirm?: { status: number; body: unknown };
}

function stubFetch(listing: ListOverrides, create?: { status: number; body: unknown }, options: StubOptions = {}) {
  const state = { listing: listing as Record<string, unknown> };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body ?? '{}')) as { name?: string };
      if (url === '/api/plugins/qbr-pack/instances') {
        if (create) return jsonResponse(create.body, create.status);
        const created = {
          schemaVersion: 1,
          instanceId: String(body.name ?? 'instance').toLowerCase().replace(/[^a-z0-9]+/g, '-'),
          name: body.name ?? 'instance',
          source: null,
          tracking: { good: 'up' },
          confirmedAt: null,
          suggested: false,
        };
        (state.listing.instances as unknown[]).push(created);
        return jsonResponse({ instance: created });
      }
      if (url.endsWith('/pick')) {
        if (options.pick) return jsonResponse(options.pick.body, options.pick.status);
        // /api/plugins/<id>/instances/<iid>/pick: echo the real instance
        // document with a staged file, exactly as the server does.
        const iid = url.split('/')[5] ?? '';
        const found = (state.listing.instances as Array<Record<string, unknown>>)
          .find((item) => item.instanceId === iid);
        const opened = found
          ? { ...found, source: { kind: 'workbook', path: '/workspace/reports/q4.xlsx', sheet: null, headerRow: 1, range: null } }
          : {
            schemaVersion: 1,
            instanceId: iid,
            name: body.name ?? iid,
            source: { kind: 'workbook', path: '/workspace/reports/q4.xlsx', sheet: null, headerRow: 1, range: null },
            tracking: { good: 'up' },
            confirmedAt: null,
            suggested: false,
          };
        return jsonResponse({ instance: opened, preview: PREVIEW, step: 'columns' });
      }
      if (url.endsWith('/confirm')) {
        if (options.confirm) return jsonResponse(options.confirm.body, options.confirm.status);
        return jsonResponse({ instance: CONFIG_INSTANCE, step: 'done' });
      }
      return jsonResponse({});
    }
    if (url.includes('/api/marketplace/plugin/')) {
      return jsonResponse(detailResponse({
        plugin: detail({ id: 'qbr-pack', name: 'QBR pack' }),
        installed: installed({ id: 'qbr-pack', name: 'QBR pack' }),
      }));
    }
    if (url.includes('/api/plugins/') && url.endsWith('/instances')) {
      return jsonResponse(state.listing);
    }
    return jsonResponse({});
  });
  vi.stubGlobal('fetch', fetchMock);
  return { fetchMock, state };
}

function postsOf(fetchMock: ReturnType<typeof vi.fn>) {
  return (fetchMock.mock.calls as [RequestInfo | URL, RequestInit | undefined][])
    .filter(([, init]) => init?.method === 'POST')
    .map(([input, init]) => ({
      url: String(input),
      body: JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>,
    }));
}

describe('the manage view configures a config-backed plugin', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/marketplace/plugin/qbr-pack/manage');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, '', '/');
  });

  it('lists the instances with their file and setup state', async () => {
    stubFetch(listing());
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Manage QBR pack' })).toBeInTheDocument();
    const section = await screen.findByRole('region', { name: 'Instances' });
    expect(within(section).getByRole('rowheader', { name: 'Pipeline' })).toBeInTheDocument();
    expect(within(section).getByText('q4.xlsx')).toBeInTheDocument();
    expect(within(section).queryByText('q4.xlsx (not confirmed)')).not.toBeInTheDocument();
    expect(within(section).getByRole('rowheader', { name: 'Board pack' })).toBeInTheDocument();
    expect(within(section).getByText('Not set up')).toBeInTheDocument();
    expect(within(section).getByRole('button', { name: 'Set up a new instance' })).toBeInTheDocument();
    expect(within(section).getByRole('button', { name: 'Edit Pipeline' })).toBeInTheDocument();
    expect(within(section).getByRole('button', { name: 'Edit Board pack' })).toBeInTheDocument();
  });

  it('leads a zero-instance panel with the Set up primary (the wizard walk lands here)', async () => {
    stubFetch(listing({ instances: [] }));
    render(<MarketplaceApp />);
    const section = await screen.findByRole('region', { name: 'Instances' });

    // The only instance row is the honest empty line; Set up comes
    // before it in the DOM, as the panel's leading primary action.
    expect(within(section).getByText(/No instances yet/)).toBeInTheDocument();
    const setUp = within(section).getByRole('button', { name: 'Set up a new instance' });
    expect(setUp).toHaveClass('btn-primary');
    const emptyCell = within(section).getByText(/No instances yet/).closest('td');
    expect(setUp.compareDocumentPosition(emptyCell as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('creates an instance from the Set up sheet and walks on to the workbook', async () => {
    const { fetchMock } = stubFetch(listing({ instances: [] }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await screen.findByRole('region', { name: 'Instances' });

    await user.click(within(section).getByRole('button', { name: 'Set up a new instance' }));
    const dialog = screen.getByRole('dialog', { name: 'Set up an instance' });
    await user.type(within(dialog).getByLabelText('Instance name'), 'Watch two');
    await user.click(within(dialog).getByRole('button', { name: 'Create instance' }));

    // The create posts; the sheet stays open and the walk continues.
    expect(postsOf(fetchMock).some((post) => post.url === '/api/plugins/qbr-pack/instances'
      && post.body.name === 'Watch two')).toBe(true);
    expect(await within(dialog).findByRole('button', { name: 'Open a workbook' })).toBeInTheDocument();
    // The list behind the sheet re-reads and shows the new instance.
    const refreshed = await screen.findByRole('region', { name: 'Instances' });
    expect(within(refreshed).getByRole('rowheader', { name: 'Watch two' })).toBeInTheDocument();
  });

  it('the full walk ends in a confirm carrying the selected rows', async () => {
    const { fetchMock } = stubFetch(listing({ instances: [] }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await screen.findByRole('region', { name: 'Instances' });

    await user.click(within(section).getByRole('button', { name: 'Set up a new instance' }));
    const dialog = screen.getByRole('dialog', { name: 'Set up an instance' });
    await user.type(within(dialog).getByLabelText('Instance name'), 'Watch two');
    await user.click(within(dialog).getByRole('button', { name: 'Create instance' }));

    // Open the workbook: the shared grid renders with the live count.
    await user.click(await within(dialog).findByRole('button', { name: 'Open a workbook' }));
    expect(await within(dialog).findByRole('columnheader', { name: 'Region' })).toBeInTheDocument();
    expect(within(dialog).getByText('2/2 rows')).toBeInTheDocument();

    // Assign on header clicks, then narrow to one row.
    await user.click(within(dialog).getByRole('radio', { name: 'Row label' }));
    await user.click(within(dialog).getByRole('button', { name: 'Region' }));
    await user.click(within(dialog).getByRole('radio', { name: 'Value column' }));
    await user.click(within(dialog).getByRole('button', { name: 'Booked' }));
    await user.click(within(dialog).getByRole('button', { name: 'Clear' }));
    await user.click(within(dialog).getByLabelText('Track row 2'));
    expect(within(dialog).getByText('1/2 rows')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Continue' }));
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    const confirm = postsOf(fetchMock).find((post) => post.url === '/api/plugins/qbr-pack/instances/watch-two/confirm');
    expect(confirm?.body.tracking).toMatchObject({
      labelColumn: 'Region',
      valueColumn: 'Booked',
      aggregate: 'sum',
      rows: [1],
    });
    // The manage view says what happened and re-reads the list.
    expect(await screen.findByText(/tracking 1 rows/)).toBeInTheDocument();
    const refreshed = screen.getByRole('region', { name: 'Instances' });
    expect(within(refreshed).getByRole('rowheader', { name: 'Watch two' })).toBeInTheDocument();
  });

  it('surfaces a refused create as a visible error, not a silent no-op', async () => {
    const { fetchMock, state } = stubFetch(listing({ instances: [] }), {
      status: 400,
      body: { error: 'config:cap', message: 'This plugin already has 6 instances.' },
    });
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await screen.findByRole('region', { name: 'Instances' });

    await user.click(within(section).getByRole('button', { name: 'Set up a new instance' }));
    const dialog = screen.getByRole('dialog', { name: 'Set up an instance' });
    await user.type(within(dialog).getByLabelText('Instance name'), 'One too many');
    await user.click(within(dialog).getByRole('button', { name: 'Create instance' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'This plugin already has 6 instances.');
    expect(within(dialog).getByRole('button', { name: 'Create instance' })).toBeInTheDocument();
    expect(postsOf(fetchMock).some((post) => post.body.name === 'One too many')).toBe(true);
    expect((state.listing.instances as unknown[]).length).toBe(0);
  });

  it('a refused confirm keeps the sheet open with the server error', async () => {
    stubFetch(listing(), undefined, {
      confirm: { status: 400, body: { error: 'config:not-granted', message: 'That selection names rows the file does not have. Open the file again.' } },
    });
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await screen.findByRole('region', { name: 'Instances' });

    await user.click(within(section).getByRole('button', { name: 'Edit Board pack' }));
    const dialog = screen.getByRole('dialog', { name: 'Edit Board pack' });
    await user.click(await within(dialog).findByRole('button', { name: 'Open a workbook' }));
    await user.click(await within(dialog).findByRole('button', { name: 'Booked' }));
    await user.click(within(dialog).getByRole('radio', { name: 'Row label' }));
    await user.click(within(dialog).getByRole('button', { name: 'Region' }));
    await user.click(within(dialog).getByRole('button', { name: 'Continue' }));
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'That selection names rows the file does not have.');
    expect(screen.getByRole('dialog', { name: 'Edit Board pack' })).toBeInTheDocument();
  });

  it('opens the workbook flow for an existing instance from Edit', async () => {
    const { fetchMock } = stubFetch(listing());
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await screen.findByRole('region', { name: 'Instances' });

    await user.click(within(section).getByRole('button', { name: 'Edit Board pack' }));
    const dialog = screen.getByRole('dialog', { name: 'Edit Board pack' });
    expect(within(dialog).getByText(/Not set up/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Open a workbook' }));
    await waitFor(() => {
      const posts = postsOf(fetchMock);
      expect(posts.some((post) =>
        post.url === '/api/plugins/qbr-pack/instances/board-pack/pick')).toBe(true);
    });
    expect(await within(dialog).findByRole('columnheader', { name: 'Booked' })).toBeInTheDocument();
    expect(within(dialog).getByText('2/2 rows')).toBeInTheDocument();
  });

  it('shows no setup entry for a plain plugin and leaves the manage view as it is', async () => {
    stubFetch(listing({ configBacked: false, instances: [] }));
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Manage QBR pack' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Instances' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Set up a new instance' })).not.toBeInTheDocument();
    // The lifecycle actions render exactly as before.
    expect(screen.getByRole('button', { name: 'Re-test' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Purge data' })).toBeInTheDocument();
  });

  it('shows an alias through its target and never offers a second config surface', async () => {
    const { fetchMock } = stubFetch(listing({
      pluginId: 'sales-delta-widget',
      aliasOf: 'excel-report',
      setupPluginId: 'excel-report',
      setupPluginName: 'Workbook tracker',
      instances: [{
        ...CONFIG_INSTANCE,
        instanceId: 'sales',
        name: 'Sales',
        source: { ...CONFIG_INSTANCE.source, path: '/workspace/reports/q4.xlsx' },
        confirmedAt: null,
      }],
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await screen.findByRole('region', { name: 'Instances' });

    expect(within(section).getByText(/runs as the Sales instance of Workbook tracker/)).toBeInTheDocument();
    expect(within(section).queryByRole('button', { name: 'Set up a new instance' })).not.toBeInTheDocument();

    await user.click(within(section).getByRole('button', { name: 'Edit Sales' }));
    const dialog = screen.getByRole('dialog', { name: 'Edit Sales' });
    await user.click(within(dialog).getByRole('button', { name: 'Open a workbook' }));
    await waitFor(() => {
      const posts = postsOf(fetchMock);
      expect(posts.some((post) =>
        post.url === '/api/plugins/excel-report/instances/sales/pick')).toBe(true);
    });
    expect(await within(dialog).findByRole('columnheader', { name: 'Region' })).toBeInTheDocument();
  });
});
