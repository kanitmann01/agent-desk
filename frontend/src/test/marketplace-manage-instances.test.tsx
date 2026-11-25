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

// The dialog's failure is its own answer (spec 009, decision 4): the
// sentence below is the server's, rendered verbatim.
const UNAVAILABLE = {
  error: 'config:picker-unavailable',
  message: "The file dialog could not open on this computer. Type the file's path, or upload the file instead.",
};
const DIALOG_NOTE = "The file dialog opens on this computer; only the file's name comes back.";

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
  // A typed path or an uploaded file opens the same preview.
  stage?: { status: number; body: unknown };
  // A static refusal, or a per-call answer (first confirm refused, the
  // retry accepted, and so on).
  confirm?: { status: number; body: unknown } | ((calls: number) => { status: number; body: unknown });
}

function confirmAnswer(options: StubOptions, calls: number): { status: number; body: unknown } | undefined {
  const step = options.confirm;
  if (typeof step === 'function') return step(calls);
  return step;
}

function stubFetch(listing: ListOverrides, create?: { status: number; body: unknown }, options: StubOptions = {}) {
  const state = { listing: listing as Record<string, unknown> };
  const confirmCalls = { count: 0 };
  // Every way in answers with the real instance document carrying a
  // staged file and the same preview, exactly as the server does.
  const opened = (iid: string, fallbackName: string) => {
    const found = (state.listing.instances as Array<Record<string, unknown>>)
      .find((item) => item.instanceId === iid);
    const document = found
      ? { ...found, source: { kind: 'workbook', path: '/workspace/reports/q4.xlsx', sheet: null, headerRow: 1, range: null } }
      : {
        schemaVersion: 1,
        instanceId: iid,
        name: fallbackName,
        source: { kind: 'workbook', path: '/workspace/reports/q4.xlsx', sheet: null, headerRow: 1, range: null },
        tracking: { good: 'up' },
        confirmedAt: null,
        suggested: false,
      };
    return { instance: document, preview: PREVIEW, step: 'columns' };
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === 'POST') {
      // An upload carries a File, so its body is never parsed as JSON.
      if (url.includes('/upload/')) {
        const answer = options.stage ?? { status: 200, body: opened(url.split('/')[5] ?? '', 'uploaded') };
        return jsonResponse(answer.body, answer.status);
      }
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
        return jsonResponse(opened(url.split('/')[5] ?? '', body.name ?? ''));
      }
      if (url.endsWith('/stage')) {
        const answer = options.stage ?? { status: 200, body: opened(url.split('/')[5] ?? '', body.name ?? '') };
        return jsonResponse(answer.body, answer.status);
      }
      if (url.endsWith('/outside')) {
        return jsonResponse({ outsideAccepted: true });
      }
      if (url.endsWith('/confirm')) {
        confirmCalls.count += 1;
        const answer = confirmAnswer(options, confirmCalls.count);
        if (answer) return jsonResponse(answer.body, answer.status);
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


/** The Instances panel once its list has landed; it is a placeholder first. */
async function loadedInstances(): Promise<HTMLElement> {
  const section = await screen.findByRole('region', { name: 'Instances' });
  await waitFor(() => expect(section).not.toHaveAttribute('aria-busy'));
  return section;
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
    const section = await loadedInstances();
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
    const section = await loadedInstances();

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
    const section = await loadedInstances();

    await user.click(within(section).getByRole('button', { name: 'Set up a new instance' }));
    const dialog = screen.getByRole('dialog', { name: 'Set up an instance' });
    await user.type(within(dialog).getByLabelText('Instance name'), 'Watch two');
    await user.click(within(dialog).getByRole('button', { name: 'Create instance' }));

    // The create posts; the sheet stays open and the walk continues.
    expect(postsOf(fetchMock).some((post) => post.url === '/api/plugins/qbr-pack/instances'
      && post.body.name === 'Watch two')).toBe(true);
    expect(await within(dialog).findByRole('button', { name: 'Open a workbook' })).toBeInTheDocument();
    // The list behind the sheet re-reads and shows the new instance.
    const refreshed = await loadedInstances();
    expect(within(refreshed).getByRole('rowheader', { name: 'Watch two' })).toBeInTheDocument();
  });

  it('the full walk ends in a confirm carrying the selected rows', async () => {
    const { fetchMock } = stubFetch(listing({ instances: [] }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await loadedInstances();

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
    const section = await loadedInstances();

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
    const section = await loadedInstances();

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

  it('an outside-workspace refusal offers the honest accept and retries the confirm', async () => {
    const { fetchMock } = stubFetch(listing(), undefined, {
      confirm: (calls: number) => (calls === 1
        ? { status: 400, body: { error: 'config:outside-workspace', message: 'That file is outside the workspace. Accept it before confirming.' } }
        : { status: 200, body: { instance: CONFIG_INSTANCE, step: 'done' } }),
    });
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await loadedInstances();

    await user.click(within(section).getByRole('button', { name: 'Edit Board pack' }));
    const dialog = screen.getByRole('dialog', { name: 'Edit Board pack' });
    await user.click(await within(dialog).findByRole('button', { name: 'Open a workbook' }));
    await user.click(await within(dialog).findByRole('button', { name: 'Booked' }));
    await user.click(within(dialog).getByRole('radio', { name: 'Row label' }));
    await user.click(within(dialog).getByRole('button', { name: 'Region' }));
    await user.click(within(dialog).getByRole('button', { name: 'Continue' }));
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }));

    // The refusal becomes the honest inline choice, not a dead end.
    expect(await within(dialog).findByText(/outside the workspace folder/)).toBeInTheDocument();
    expect(within(dialog).queryByRole('alert')).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Use it anyway' }));

    // The acceptance posts once, then the same confirm retries and lands.
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const posts = postsOf(fetchMock);
    expect(posts.some((post) => post.url.endsWith('/instances/board-pack/outside'))).toBe(true);
    const confirmPosts = posts.filter((post) => post.url.endsWith('/instances/board-pack/confirm'));
    expect(confirmPosts.length).toBe(2);
    expect(await screen.findByText(/tracking 2 rows/)).toBeInTheDocument();
  });

  it('opens the workbook flow for an existing instance from Edit', async () => {
    const { fetchMock } = stubFetch(listing());
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await loadedInstances();

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
    // The panel keeps a placeholder while the list is read; once the server
    // says this plugin is not config-backed it drops away.
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Instances' })).not.toBeInTheDocument());
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
    const section = await loadedInstances();

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

  it('a dialog that could not open in create mode shows the sentence, drops the note and opens the block', async () => {
    stubFetch(listing({ instances: [] }), undefined, { pick: { status: 503, body: UNAVAILABLE } });
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await loadedInstances();

    await user.click(within(section).getByRole('button', { name: 'Set up a new instance' }));
    const dialog = screen.getByRole('dialog', { name: 'Set up an instance' });
    await user.type(within(dialog).getByLabelText('Instance name'), 'Watch two');
    await user.click(within(dialog).getByRole('button', { name: 'Create instance' }));

    // A fresh Open step shows the dialog note, collapsed.
    const open = await within(dialog).findByRole('button', { name: 'Open a workbook' });
    expect(within(dialog).getByText(DIALOG_NOTE)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Type a path or upload instead' }))
      .toHaveAttribute('aria-expanded', 'false');
    await user.click(open);

    expect(await within(dialog).findByText(UNAVAILABLE.message)).toBeInTheDocument();
    // The dialog did not open, so the note about it stops being true.
    expect(within(dialog).queryByText(DIALOG_NOTE)).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Type a path or upload instead' }))
      .toHaveAttribute('aria-expanded', 'true');
    expect(within(dialog).getByLabelText('Workbook path')).toBeVisible();
    expect(within(dialog).getByLabelText('Workbook file')).toBeVisible();
    // The dialog keeps its place and its wording.
    expect(within(dialog).getByRole('button', { name: 'Open a workbook' })).toBeInTheDocument();
  });

  it('the edit sheet shows the same sentence and drops the note as well', async () => {
    stubFetch(listing(), undefined, { pick: { status: 503, body: UNAVAILABLE } });
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await loadedInstances();

    await user.click(within(section).getByRole('button', { name: 'Edit Board pack' }));
    const dialog = screen.getByRole('dialog', { name: 'Edit Board pack' });
    expect(within(dialog).getByText(DIALOG_NOTE)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Open a workbook' }));

    expect(await within(dialog).findByText(UNAVAILABLE.message)).toBeInTheDocument();
    expect(within(dialog).queryByText(DIALOG_NOTE)).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Type a path or upload instead' }))
      .toHaveAttribute('aria-expanded', 'true');
    expect(within(dialog).getByLabelText('Workbook path')).toBeVisible();
    expect(within(dialog).getByLabelText('Workbook file')).toBeVisible();
  });

  it('a typed path posts to stage and lands on the columns step', async () => {
    const { fetchMock } = stubFetch(listing({ instances: [] }), undefined, {
      pick: { status: 503, body: UNAVAILABLE },
    });
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await loadedInstances();

    await user.click(within(section).getByRole('button', { name: 'Set up a new instance' }));
    const dialog = screen.getByRole('dialog', { name: 'Set up an instance' });
    await user.type(within(dialog).getByLabelText('Instance name'), 'Watch two');
    await user.click(within(dialog).getByRole('button', { name: 'Create instance' }));
    await user.click(await within(dialog).findByRole('button', { name: 'Open a workbook' }));

    expect(await within(dialog).findByRole('button', { name: 'Use this path' })).toBeDisabled();
    const path = within(dialog).getByLabelText('Workbook path');
    await user.type(path, '   ');
    expect(within(dialog).getByRole('button', { name: 'Use this path' })).toBeDisabled();
    await user.clear(path);
    await user.type(path, '/workspace/reports/q4.xlsx');
    await user.click(within(dialog).getByRole('button', { name: 'Use this path' }));

    // The same tail as a successful pick: every row starts selected.
    expect(await within(dialog).findByRole('columnheader', { name: 'Region' })).toBeInTheDocument();
    expect(within(dialog).getByText('2/2 rows')).toBeInTheDocument();
    const stage = postsOf(fetchMock).find((post) =>
      post.url === '/api/plugins/qbr-pack/instances/watch-two/stage');
    expect(stage?.body).toEqual({ path: '/workspace/reports/q4.xlsx' });
  });

  it('a chosen file uploads as octet-stream and lands on the columns step', async () => {
    const { fetchMock } = stubFetch(listing());
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await loadedInstances();

    await user.click(within(section).getByRole('button', { name: 'Edit Board pack' }));
    const dialog = screen.getByRole('dialog', { name: 'Edit Board pack' });
    // The block is always one disclosure away, even without a refusal.
    await user.click(within(dialog).getByRole('button', { name: 'Type a path or upload instead' }));
    const file = new File(['bytes'], 'q4.xlsx');
    await user.upload(within(dialog).getByLabelText('Workbook file'), file);
    expect(within(dialog).getByRole('button', { name: 'Upload this file' })).toBeEnabled();
    await user.click(within(dialog).getByRole('button', { name: 'Upload this file' }));

    expect(await within(dialog).findByRole('columnheader', { name: 'Region' })).toBeInTheDocument();
    expect(within(dialog).getByText('2/2 rows')).toBeInTheDocument();
    // A File body is not JSON, so the sent request is read off the mock.
    const uploadCall = fetchMock.mock.calls
      .find(([target]) => String(target).endsWith('/instances/board-pack/upload/q4.xlsx'));
    expect(String(uploadCall?.[0])).toBe('/api/plugins/qbr-pack/instances/board-pack/upload/q4.xlsx');
    const uploadInit = uploadCall?.[1];
    expect(uploadInit?.method).toBe('POST');
    const headers = uploadInit?.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/octet-stream');
    expect(uploadInit?.body).toBe(file);
  });

  it('a cancelled dialog keeps the note and the block collapsed, still one click away', async () => {
    stubFetch(listing(), undefined, {
      pick: { status: 400, body: { error: 'config:cancelled', message: 'No file was opened.' } },
    });
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    const section = await loadedInstances();

    await user.click(within(section).getByRole('button', { name: 'Edit Board pack' }));
    const dialog = screen.getByRole('dialog', { name: 'Edit Board pack' });
    await user.click(within(dialog).getByRole('button', { name: 'Open a workbook' }));

    expect(await within(dialog).findByText('No file was opened.')).toBeInTheDocument();
    expect(within(dialog).getByText(DIALOG_NOTE)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Type a path or upload instead' }))
      .toHaveAttribute('aria-expanded', 'false');
    expect(within(dialog).queryByLabelText('Workbook path')).not.toBeInTheDocument();

    // A genuine Cancel is one click away from the same two ways in.
    await user.click(within(dialog).getByRole('button', { name: 'Type a path or upload instead' }));
    expect(within(dialog).getByLabelText('Workbook path')).toBeVisible();
    expect(within(dialog).getByRole('button', { name: 'Type a path or upload instead' }))
      .toHaveAttribute('aria-expanded', 'true');
  });
});
