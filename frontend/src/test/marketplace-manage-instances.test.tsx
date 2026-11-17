// The manage view's instance setup (T5): a config-backed plugin lists its
// instances with Set up and Edit against the same endpoints the dashboard
// card drives; a plain plugin shows no setup entry; a refused action
// surfaces the server's error, never a silent no-op.
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

function stubFetch(listing: ListOverrides, create?: { status: number; body: unknown }) {
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
        const opened = {
          ...CONFIG_INSTANCE,
          source: { ...CONFIG_INSTANCE.source },
        };
        return jsonResponse({ instance: opened, preview: { headers: ['Region', 'Booked'], rows: [] }, step: 'columns' });
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

  it('creates an instance from the Set up sheet and refreshes the list', async () => {
    const { fetchMock } = stubFetch(listing({ instances: [] }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await screen.findByRole('region', { name: 'Instances' });

    await user.click(within(section).getByRole('button', { name: 'Set up a new instance' }));
    const dialog = screen.getByRole('dialog', { name: 'Set up an instance' });
    await user.type(within(dialog).getByLabelText('Instance name'), 'Watch two');
    await user.click(within(dialog).getByRole('button', { name: 'Create instance' }));

    await waitFor(() => {
      const posts = postsOf(fetchMock);
      expect(posts.some((post) => post.url === '/api/plugins/qbr-pack/instances'
        && post.body.name === 'Watch two')).toBe(true);
    });
    const refreshed = await screen.findByRole('region', { name: 'Instances' });
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

  it('opens the workbook flow for an existing instance from Edit', async () => {
    const { fetchMock } = stubFetch(listing());
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await screen.findByRole('region', { name: 'Instances' });

    await user.click(within(section).getByRole('button', { name: 'Edit Board pack' }));
    const dialog = screen.getByRole('dialog', { name: 'Edit Board pack' });
    expect(within(dialog).getByText('Not set up')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Open workbook' }));
    await waitFor(() => {
      const posts = postsOf(fetchMock);
      expect(posts.some((post) =>
        post.url === '/api/plugins/qbr-pack/instances/board-pack/pick')).toBe(true);
    });
    expect(await within(dialog).findByText('q4.xlsx')).toBeInTheDocument();
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
    await user.click(within(dialog).getByRole('button', { name: 'Open workbook' }));
    await waitFor(() => {
      const posts = postsOf(fetchMock);
      expect(posts.some((post) =>
        post.url === '/api/plugins/excel-report/instances/sales/pick')).toBe(true);
    });
  });
});
