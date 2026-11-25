// The review's marketplace defects: one action at a time across rows, detail
// reads that do not fan out on every list reload, dialogs that keep a failure
// inside the sheet, retries that show their own wait, an outcome announced
// after a sheet closed mid-request, and the cannot-run notice where the
// decision is made.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { BUSY_WATCHDOG_MS, BUSY_WATCHDOG_TEXT } from '../marketplace/useBusyWatchdog';
import { card, catalog, detail, detailResponse, installed, installedResponse } from './marketplace-fixtures';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

interface Deferred<T> {
  promise: Promise<T>;
  release: (value: T) => void;
}

/** One promise and the function that completes it, for a held request. */
function deferred<T>(): Deferred<T> {
  let release: (value: T) => void = () => {};
  const promise = new Promise<T>((resolve) => { release = resolve; });
  return { promise, release };
}

const WEB_CAPABILITIES = {
  sources: ['http-get'],
  permissions: ['network.allow: example.com'],
  elementKinds: ['list'],
  filesystem: [],
  network: ['example.com'],
};

const NONWEB_CAPABILITIES = {
  sources: ['excel-watch'],
  permissions: [],
  elementKinds: ['metric'],
  filesystem: [],
  network: [],
};

const NOTICE = 'This desk cannot read web pages yet, so this plugin cannot run here.';

function adminSnapshot(pending: unknown[]) {
  return {
    posture: {
      mode: 'curated', riskCeiling: 'T1', requireSignatures: true,
      killSwitch: [] as string[], allowedPublishers: [], allowedCategories: [],
      networkAllowlist: [], enabledSources: ['bundled', 'org', 'peer'],
    },
    anchor: { epoch: 3, fingerprints: ['a24fafdbac6e'] },
    policy: { signatureStatus: 'unsigned', warning: null, epoch: 0, signerFingerprint: null, expiresAt: null },
    pending,
    revoked: [],
    inventory: [],
    catalogSource: 'bundled',
    auditEvents: 4,
  };
}

function publication(id: string, pluginId: string) {
  return {
    id, pluginId, version: '1.0.0', publisher: 'agent-desk',
    submittedAt: '2026-11-15T12:00:00Z', changelog: `Adds ${pluginId}.`,
  };
}

describe('the review defects', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    window.localStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('M2: keeps every row inert while any installed action is in flight', async () => {
    window.history.replaceState({}, '', '/marketplace/installed');
    const disable = deferred<Response>();
    const records = [
      installed({ id: 'ar-aging', name: 'AR Aging' }),
      installed({ id: 'desk-snapshot', name: 'Desk snapshot' }),
    ];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/disable')) return disable.promise;
      return jsonResponse(installedResponse(records));
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'AR Aging' });
    const first = screen.getByRole('heading', { level: 2, name: 'AR Aging' }).closest('article') as HTMLElement;
    const second = screen.getByRole('heading', { level: 2, name: 'Desk snapshot' }).closest('article') as HTMLElement;

    await user.click(within(first).getByRole('button', { name: 'Disable' }));
    await within(first).findByRole('button', { name: 'Disabling…' });

    // A second row cannot start its own action while the first is running.
    const secondDisable = within(second).getByRole('button', { name: 'Disable' });
    expect(secondDisable).toBeDisabled();
    await user.click(secondDisable);

    // The first row keeps its pending state and the press changed nothing.
    const stillPending = within(first).getByRole('button', { name: 'Disabling…' });
    await waitFor(() => expect(stillPending).toHaveAttribute('aria-busy', 'true'));
    expect(first).toHaveAttribute('aria-busy', 'true');

    await act(async () => { disable.release(jsonResponse({ id: 'ar-aging', state: 'disabled' })); });
    expect(await screen.findByText('AR Aging is now disabled.')).toBeInTheDocument();
  });

  it('M2: keeps every admin row inert while any decision is in flight', async () => {
    window.history.replaceState({}, '', '/marketplace/admin');
    const approve = deferred<Response>();
    const pending = [publication('pub-1', 'widget-one'), publication('pub-2', 'widget-two')];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/approve')) return approve.promise;
      return jsonResponse(adminSnapshot(pending));
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'Pending publications' });
    await user.click(screen.getByRole('button', { name: 'Approve widget-one' }));
    await screen.findByRole('button', { name: 'Approving…' });

    const secondApprove = screen.getByRole('button', { name: 'Approve widget-two' });
    expect(secondApprove).toBeDisabled();
    const secondReject = screen.getByRole('button', { name: 'Reject widget-two' });
    expect(secondReject).toBeDisabled();
    await user.click(secondApprove);

    expect(screen.getByRole('button', { name: 'Approving…' })).toHaveAttribute('aria-busy', 'true');

    await act(async () => { approve.release(jsonResponse({ ok: true, id: 'pub-1', decision: 'approve', pluginId: 'widget-one' })); });
    expect(await screen.findByText('Approved widget-one. It is now in the organization catalog.')).toBeInTheDocument();
  });

  it('M3: reads each installed plugin detail once per installed set', async () => {
    window.history.replaceState({}, '', '/marketplace/installed');
    let record = installed({ id: 'ar-aging', name: 'AR Aging' });
    let detailCalls = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/disable')) {
        record = installed({ id: 'ar-aging', name: 'AR Aging', enabled: false });
        return jsonResponse({ id: 'ar-aging', state: 'disabled' });
      }
      if (url.includes('/api/marketplace/plugin/')) {
        detailCalls += 1;
        return jsonResponse(detailResponse({
          plugin: detail({ id: 'ar-aging', name: 'AR Aging', capabilities: NONWEB_CAPABILITIES }),
          installed: record,
          deskNetwork: false,
        }));
      }
      return jsonResponse(installedResponse([record], false));
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'AR Aging' });
    await waitFor(() => expect(detailCalls).toBe(1));

    await user.click(screen.getByRole('button', { name: 'Disable' }));
    expect(await screen.findByText('AR Aging is now disabled.')).toBeInTheDocument();
    // The reload rendered the new record; the same id set must not re-read
    // the detail.
    await screen.findByRole('button', { name: 'Enable' });
    await act(async () => { await Promise.resolve(); });
    expect(detailCalls).toBe(1);
  });

  it('M4: keeps the installed confirm open with a failure, then closes on success', async () => {
    window.history.replaceState({}, '', '/marketplace/installed');
    let calls = 0;
    let record = installed({ id: 'ar-aging', name: 'AR Aging' });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/rollback')) {
        calls += 1;
        if (calls === 1) {
          return jsonResponse({ error: 'marketplace:refused', message: 'The rollback was refused.' }, 400);
        }
        record = installed({ id: 'ar-aging', name: 'AR Aging', pinned: { version: '1.1.0', sha256: 'b'.repeat(64) } });
        return jsonResponse({ id: 'ar-aging', from: '1.2.0', to: '1.1.0' });
      }
      return jsonResponse(installedResponse([record]));
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'AR Aging' });
    await user.click(screen.getByRole('button', { name: 'Roll back' }));
    const dialog = screen.getByRole('dialog', { name: 'Roll back AR Aging' });
    await user.click(within(dialog).getByRole('button', { name: 'Roll back' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The rollback was refused.');
    expect(screen.getByRole('dialog', { name: 'Roll back AR Aging' })).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Roll back' }));
    expect(await screen.findByText('Rolled back AR Aging from 1.2.0 to 1.1.0.')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('M4: keeps the detail confirm open with a failure, then closes on success', async () => {
    window.history.replaceState({}, '', '/marketplace/plugin/ar-aging');
    let calls = 0;
    let installedState = installed({ id: 'ar-aging', name: 'AR Aging' });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/rollback')) {
        calls += 1;
        if (calls === 1) {
          return jsonResponse({ error: 'marketplace:refused', message: 'The rollback was refused.' }, 400);
        }
        installedState = installed({
          id: 'ar-aging', name: 'AR Aging', pinned: { version: '1.1.0', sha256: 'b'.repeat(64) },
        });
        return jsonResponse({ id: 'ar-aging', from: '1.2.0', to: '1.1.0' });
      }
      return jsonResponse(detailResponse({ installed: installedState }));
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 1, name: 'AR Aging' });
    await user.click(screen.getByRole('button', { name: 'Roll back' }));
    const dialog = screen.getByRole('dialog', { name: 'Roll back plugin' });
    await user.click(within(dialog).getByRole('button', { name: 'Roll back' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The rollback was refused.');
    expect(screen.getByRole('dialog', { name: 'Roll back plugin' })).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Roll back' }));
    expect(await screen.findByText('Rolled back from 1.2.0 to 1.1.0.')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('M5: shows the installed retry working and refuses a second press', async () => {
    window.history.replaceState({}, '', '/marketplace/installed');
    const retry = deferred<Response>();
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls += 1;
      if (calls === 1) return jsonResponse({ error: 'boom', message: 'The list is unavailable.' }, 500);
      return retry.promise;
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { name: 'The installed list did not load' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    const pending = await screen.findByRole('button', { name: 'Trying again…' });
    await waitFor(() => expect(pending).toHaveAttribute('aria-busy', 'true'));
    expect(pending).toBeDisabled();

    await act(async () => { retry.release(jsonResponse(installedResponse([installed()]))); });
    expect(await screen.findByRole('heading', { level: 2, name: 'AR Aging' })).toBeInTheDocument();
  });

  it('M5: shows the admin retry working and refuses a second press', async () => {
    window.history.replaceState({}, '', '/marketplace/admin');
    const retry = deferred<Response>();
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls += 1;
      if (calls === 1) return jsonResponse({ error: 'boom', message: 'The snapshot is unavailable.' }, 500);
      return retry.promise;
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { name: 'The admin snapshot could not be loaded' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    const pending = await screen.findByRole('button', { name: 'Trying again…' });
    await waitFor(() => expect(pending).toHaveAttribute('aria-busy', 'true'));
    expect(pending).toBeDisabled();

    await act(async () => { retry.release(jsonResponse(adminSnapshot([]))); });
    expect(await screen.findByRole('heading', { level: 2, name: 'Posture' })).toBeInTheDocument();
  });

  it('M6: announces a setup outcome after the sheet closed mid-request', async () => {
    window.history.replaceState({}, '', '/marketplace/plugin/qbr-pack/manage');
    const confirm = deferred<Response>();
    const instance = {
      schemaVersion: 1, instanceId: 'board-pack', name: 'Board pack',
      source: null, tracking: { good: 'up' }, confirmedAt: null, suggested: false,
    };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/confirm')) return confirm.promise;
      if (init?.method === 'POST' && url.endsWith('/pick')) {
        return jsonResponse({
          instance: {
            ...instance,
            source: { kind: 'workbook', path: '/workspace/reports/q4.xlsx', sheet: null, headerRow: 1, range: null },
          },
          preview: { headers: ['Region', 'Booked'], rows: [['East', '10'], ['West', '5']], sheet: 'Data' },
          step: 'columns',
        });
      }
      if (url.includes('/api/marketplace/plugin/')) {
        return jsonResponse(detailResponse({
          plugin: detail({ id: 'qbr-pack', name: 'QBR pack' }),
          installed: installed({ id: 'qbr-pack', name: 'QBR pack' }),
        }));
      }
      if (url.includes('/api/plugins/') && url.endsWith('/instances')) {
        return jsonResponse({
          pluginId: 'qbr-pack', configBacked: true, aliasOf: null,
          setupPluginId: 'qbr-pack', setupPluginName: 'QBR pack', instances: [instance],
        });
      }
      return jsonResponse({});
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 1, name: 'Manage QBR pack' });
    const section = await screen.findByRole('region', { name: 'Instances' });
    await waitFor(() => expect(section).not.toHaveAttribute('aria-busy'));
    await user.click(within(section).getByRole('button', { name: 'Edit Board pack' }));

    const dialog = screen.getByRole('dialog', { name: 'Edit Board pack' });
    await user.click(await within(dialog).findByRole('button', { name: 'Open a workbook' }));
    await user.click(await within(dialog).findByRole('button', { name: 'Booked' }));
    await user.click(within(dialog).getByRole('radio', { name: 'Row label' }));
    await user.click(within(dialog).getByRole('button', { name: 'Region' }));
    await user.click(within(dialog).getByRole('button', { name: 'Continue' }));
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }));

    // The reader leaves before the server answers; the outcome still lands on
    // the page they returned to.
    await user.click(within(dialog).getByRole('button', { name: 'Close dialog' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await act(async () => {
      confirm.release(jsonResponse({
        error: 'config:not-granted',
        message: 'That selection names rows the file does not have.',
      }, 400));
    });
    expect(await screen.findByText(
      'The tracker was not saved: That selection names rows the file does not have.',
    )).toBeInTheDocument();
  });

  it('M7: says a plugin cannot run in the install consent sheet, above the accept button', async () => {
    window.history.replaceState({}, '', '/marketplace/plugin/competitor-watch');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(detailResponse({
      plugin: detail({
        id: 'competitor-watch', name: 'Competitor Watch', capabilities: WEB_CAPABILITIES,
      }),
      deskNetwork: false,
    }))));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 1, name: 'Competitor Watch' });
    await user.click(screen.getByRole('button', { name: 'Install plugin' }));
    const dialog = screen.getByRole('dialog', { name: 'Install Competitor Watch' });
    const notice = within(dialog).getByText(NOTICE);
    const accept = within(dialog).getByRole('button', { name: 'Install plugin' });
    expect(notice.compareDocumentPosition(accept) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('M7: marks a catalog card that cannot run on this desk', async () => {
    window.history.replaceState({}, '', '/marketplace');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(catalog([
      card({
        id: 'competitor-watch', name: 'Competitor Watch', category: 'research',
        capabilities: WEB_CAPABILITIES,
      }),
      card({ id: 'ar-aging', name: 'AR Aging' }),
    ], false))));
    render(<MarketplaceApp />);

    expect(await screen.findByText('Competitor Watch')).toBeInTheDocument();
    expect(screen.getAllByText('Cannot run on this desk')).toHaveLength(1);
  });

  it('M7: shows no catalog chip when the card carries no capability field', async () => {
    window.history.replaceState({}, '', '/marketplace');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(catalog([
      card({ id: 'competitor-watch', name: 'Competitor Watch', category: 'research' }),
    ], false))));
    render(<MarketplaceApp />);

    expect(await screen.findByText('Competitor Watch')).toBeInTheDocument();
    expect(screen.queryByText('Cannot run on this desk')).not.toBeInTheDocument();
  });
});

// The second review: the detail page and the catalog card must agree on a
// refused plugin, a detail header must agree with the Installed row for a
// plugin that cannot run, the web answer must follow the pinned version, and
// a purge dialog must not let the reader cancel out of its own failure.
const POLICY_HELP = "Only whoever manages this desk's plugin policy can change that; there is no setting for it here.";

const POLICY_REASONS = [
  { code: 'policy:network', message: "network host 'example.com' is not on the policy allowlist" },
  { code: 'policy:risk', message: 'risk tier T2 exceeds the policy ceiling T1' },
];

/** Escape a literal for use inside a RegExp. */
function literal(text: string): RegExp {
  return new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
}

describe('the second review defects', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    window.localStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('M1: shows every policy reason, in the card words, where install is refused', async () => {
    window.history.replaceState({}, '', '/marketplace/plugin/competitor-watch');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(detailResponse({
      plugin: detail({
        id: 'competitor-watch', name: 'Competitor Watch',
        capabilities: WEB_CAPABILITIES, eligible: false,
        ineligibleReasons: POLICY_REASONS,
      }),
      deskNetwork: true,
    }))));
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 1, name: 'Competitor Watch' });
    for (const reason of POLICY_REASONS) {
      expect(screen.getByText(literal(reason.message))).toBeInTheDocument();
    }
    expect(screen.getAllByText('Not available:')).toHaveLength(POLICY_REASONS.length);
    expect(screen.getByText(POLICY_HELP)).toBeInTheDocument();
    expect(screen.queryByText('This plugin is not available under the current policy.'))
      .not.toBeInTheDocument();
  });

  it('M2: a cannot-run installed detail offers the notice with Uninstall and Purge data', async () => {
    window.history.replaceState({}, '', '/marketplace/plugin/competitor-watch');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(detailResponse({
      plugin: detail({
        id: 'competitor-watch', name: 'Competitor Watch', capabilities: WEB_CAPABILITIES,
      }),
      installed: installed({ id: 'competitor-watch', name: 'Competitor Watch' }),
      deskNetwork: false,
    }))));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    const heading = await screen.findByRole('heading', { level: 1, name: 'Competitor Watch' });
    const header = heading.closest('header') as HTMLElement;
    expect(within(header).getByText(NOTICE)).toBeInTheDocument();
    expect(within(header).getAllByRole('button').map((button) => button.textContent?.trim()))
      .toEqual(['Uninstall', 'Purge data']);
    expect(within(header).queryByRole('button', { name: 'Disable' })).not.toBeInTheDocument();
    expect(within(header).queryByRole('button', { name: 'Roll back' })).not.toBeInTheDocument();

    await user.click(within(header).getByRole('button', { name: 'Purge data' }));
    const purge = await screen.findByRole('dialog', { name: 'Purge plugin data' });
    expect(within(purge).getByRole('button', { name: 'Purge data' })).toBeDisabled();
    await user.click(within(purge).getByRole('button', { name: 'Cancel' }));

    await user.click(within(header).getByRole('button', { name: 'Uninstall' }));
    expect(await screen.findByRole('dialog', { name: 'Uninstall plugin' })).toBeInTheDocument();
  });

  it('M3: reads the detail again when a rollback changes the pinned version', async () => {
    window.history.replaceState({}, '', '/marketplace/installed');
    let pinned = '1.2.0';
    const detailVersions: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/rollback')) {
        pinned = '1.1.0';
        return jsonResponse({ id: 'ar-aging', from: '1.2.0', to: '1.1.0' });
      }
      if (url.includes('/api/marketplace/plugin/')) {
        detailVersions.push(pinned);
        return jsonResponse(detailResponse({
          plugin: detail({
            id: 'ar-aging', name: 'AR Aging',
            capabilities: pinned === '1.1.0' ? WEB_CAPABILITIES : NONWEB_CAPABILITIES,
          }),
          installed: installed({
            id: 'ar-aging', name: 'AR Aging',
            pinned: { version: pinned, sha256: 'a'.repeat(64) },
          }),
          deskNetwork: false,
        }));
      }
      return jsonResponse(installedResponse([installed({
        id: 'ar-aging', name: 'AR Aging',
        pinned: { version: pinned, sha256: 'a'.repeat(64) },
      })], false));
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'AR Aging' });
    await waitFor(() => expect(detailVersions).toEqual(['1.2.0']));

    await user.click(screen.getByRole('button', { name: 'Roll back' }));
    const dialog = screen.getByRole('dialog', { name: 'Roll back AR Aging' });
    await user.click(within(dialog).getByRole('button', { name: 'Roll back' }));

    expect(await screen.findByText('Rolled back AR Aging from 1.2.0 to 1.1.0.')).toBeInTheDocument();
    // The new pinned version asks for the web, so a fresh capability read
    // turns the row into the cannot-run state.
    expect(await screen.findByText('Cannot run on this desk')).toBeInTheDocument();
    await waitFor(() => expect(detailVersions).toContain('1.1.0'));
  });

  it('M4: keeps the installed purge dialog through a failure and refuses a cancel in flight', async () => {
    window.history.replaceState({}, '', '/marketplace/installed');
    const purge = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/purge-data')) return purge.promise;
      return jsonResponse(installedResponse([installed()]));
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'AR Aging' });
    await user.click(screen.getByRole('button', { name: 'Purge data' }));
    const dialog = screen.getByRole('dialog', { name: 'Purge data for AR Aging' });
    await user.type(
      within(dialog).getByLabelText(/Type delete-data:ar-aging to confirm/),
      'delete-data:ar-aging',
    );
    await user.click(within(dialog).getByRole('button', { name: 'Purge data' }));

    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await act(async () => {
      purge.release(jsonResponse({
        error: 'marketplace:refused', message: 'The purge was refused.',
      }, 400));
    });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The purge was refused.');
    expect(screen.getByRole('dialog', { name: 'Purge data for AR Aging' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeEnabled();
  });

  it('M4: keeps the detail purge dialog through a failure and refuses a cancel in flight', async () => {
    window.history.replaceState({}, '', '/marketplace/plugin/ar-aging');
    const purge = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/purge-data')) return purge.promise;
      return jsonResponse(detailResponse({ installed: installed() }));
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 1, name: 'AR Aging' });
    await user.click(screen.getByRole('button', { name: 'Purge data' }));
    const dialog = screen.getByRole('dialog', { name: 'Purge plugin data' });
    await user.type(
      within(dialog).getByLabelText(/Type delete-data:ar-aging to confirm/),
      'delete-data:ar-aging',
    );
    await user.click(within(dialog).getByRole('button', { name: 'Purge data' }));

    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await act(async () => {
      purge.release(jsonResponse({
        error: 'marketplace:refused', message: 'The purge was refused.',
      }, 400));
    });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The purge was refused.');
    expect(screen.getByRole('dialog', { name: 'Purge plugin data' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeEnabled();
  });
});

// The fifth review: a stuck request must not lock a sheet forever, and a late
// answer must still be said on the page the reader returned to.
describe('the fifth review defects', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    window.localStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  /** Let pending promises and effects settle under fake timers. */
  async function settle(): Promise<void> {
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  }

  it('M8: releases the installed purge dialog after the watchdog and announces a late failure', async () => {
    vi.useFakeTimers();
    window.history.replaceState({}, '', '/marketplace/installed');
    const purge = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/purge-data')) return purge.promise;
      return jsonResponse(installedResponse([installed()]));
    }));
    render(<MarketplaceApp />);
    await settle();

    fireEvent.click(screen.getByRole('button', { name: 'Purge data' }));
    const dialog = screen.getByRole('dialog', { name: 'Purge data for AR Aging' });
    fireEvent.change(
      within(dialog).getByLabelText(/Type delete-data:ar-aging to confirm/),
      { target: { value: 'delete-data:ar-aging' } },
    );
    fireEvent.click(within(dialog).getByRole('button', { name: 'Purge data' }));

    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    expect(cancel).toBeDisabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(BUSY_WATCHDOG_MS - 1); });
    expect(cancel).toBeDisabled();
    expect(within(dialog).queryByText(BUSY_WATCHDOG_TEXT)).toBeNull();

    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(within(dialog).getByText(BUSY_WATCHDOG_TEXT)).toBeInTheDocument();
    expect(cancel).toBeEnabled();
    expect(within(dialog).getByRole('button', { name: 'Purging…' })).toBeDisabled();

    fireEvent.click(cancel);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await act(async () => {
      purge.release(jsonResponse({
        error: 'marketplace:refused', message: 'The purge was refused.',
      }, 400));
    });
    await settle();
    expect(screen.getByText('The purge was refused.')).toBeInTheDocument();
  });

  it('M8: a late purge success still refetches the list and says so', async () => {
    vi.useFakeTimers();
    window.history.replaceState({}, '', '/marketplace/installed');
    const purge = deferred<Response>();
    let purged = false;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/purge-data')) return purge.promise;
      return jsonResponse(installedResponse(purged ? [] : [installed()]));
    }));
    render(<MarketplaceApp />);
    await settle();

    fireEvent.click(screen.getByRole('button', { name: 'Purge data' }));
    const dialog = screen.getByRole('dialog', { name: 'Purge data for AR Aging' });
    fireEvent.change(
      within(dialog).getByLabelText(/Type delete-data:ar-aging to confirm/),
      { target: { value: 'delete-data:ar-aging' } },
    );
    fireEvent.click(within(dialog).getByRole('button', { name: 'Purge data' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(BUSY_WATCHDOG_MS); });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    purged = true;
    await act(async () => { purge.release(jsonResponse({ ok: true, purged: 'ar-aging' })); });
    await settle();
    await settle();
    expect(screen.getByText('AR Aging data purged.')).toBeInTheDocument();
    expect(screen.getByText('Nothing is installed yet.')).toBeInTheDocument();
  });

  it('M8: releases the detail purge dialog after the watchdog and announces a late failure', async () => {
    vi.useFakeTimers();
    window.history.replaceState({}, '', '/marketplace/plugin/ar-aging');
    const purge = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/purge-data')) return purge.promise;
      return jsonResponse(detailResponse({ installed: installed() }));
    }));
    render(<MarketplaceApp />);
    await settle();

    fireEvent.click(screen.getByRole('button', { name: 'Purge data' }));
    const dialog = screen.getByRole('dialog', { name: 'Purge plugin data' });
    fireEvent.change(
      within(dialog).getByLabelText(/Type delete-data:ar-aging to confirm/),
      { target: { value: 'delete-data:ar-aging' } },
    );
    fireEvent.click(within(dialog).getByRole('button', { name: 'Purge data' }));
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    expect(cancel).toBeDisabled();

    await act(async () => { await vi.advanceTimersByTimeAsync(BUSY_WATCHDOG_MS); });
    expect(within(dialog).getByText(BUSY_WATCHDOG_TEXT)).toBeInTheDocument();
    expect(cancel).toBeEnabled();
    fireEvent.click(cancel);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await act(async () => {
      purge.release(jsonResponse({
        error: 'marketplace:refused', message: 'The purge was refused.',
      }, 400));
    });
    await settle();
    expect(screen.getByText('The purge was refused.')).toBeInTheDocument();
  });

  it('M8: releases the installed confirm dialog after the watchdog and announces a late failure', async () => {
    vi.useFakeTimers();
    window.history.replaceState({}, '', '/marketplace/installed');
    const rollback = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/rollback')) return rollback.promise;
      return jsonResponse(installedResponse([installed()]));
    }));
    render(<MarketplaceApp />);
    await settle();

    fireEvent.click(screen.getByRole('button', { name: 'Roll back' }));
    const dialog = screen.getByRole('dialog', { name: 'Roll back AR Aging' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Roll back' }));
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    expect(cancel).toBeDisabled();

    await act(async () => { await vi.advanceTimersByTimeAsync(BUSY_WATCHDOG_MS); });
    expect(within(dialog).getByText(BUSY_WATCHDOG_TEXT)).toBeInTheDocument();
    expect(cancel).toBeEnabled();
    expect(within(dialog).getByRole('button', { name: 'Rolling back…' })).toBeDisabled();
    fireEvent.click(cancel);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await act(async () => {
      rollback.release(jsonResponse({
        error: 'marketplace:refused', message: 'The rollback was refused.',
      }, 400));
    });
    await settle();
    expect(screen.getByText('The rollback was refused.')).toBeInTheDocument();
  });
});
