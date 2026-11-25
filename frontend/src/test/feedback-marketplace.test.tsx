// Spec 027 in the marketplace: every wait says something. A control that
// starts work shows it on itself after 100 ms (aria-busy, the continuous
// verb, no second press); a region that will receive a result shows a
// same-shape placeholder; a refetch keeps what is on screen; a 401 says the
// session expired instead of showing an empty list and a try that cannot
// work.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { card, catalog, detail, detailResponse, installed, installedResponse } from './marketplace-fixtures';

const here = dirname(fileURLToPath(import.meta.url));
const marketplaceCss = readFileSync(resolve(here, '..', 'marketplace', 'marketplace.css'), 'utf8');

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

const TRUST = {
  anchor: { epoch: 3, fingerprints: ['a24fafdbac6e'] },
  policy: {
    mode: 'open', source: 'signed', signatureStatus: 'signed', warning: null,
    epoch: 3, signerFingerprint: 'deadbeef', expiresAt: '2027-11-15T12:00:00Z',
  },
  lastValidatorRun: { at: null, ok: null, failures: [], scope: null },
  guarantees: ['Every release is checked against its signed digest before it can become eligible.'],
  cannotHappen: ['A tampered or expired policy can never be applied by the marketplace.'],
  reportPath: '/marketplace/report',
};

const ADMIN = {
  posture: {
    mode: 'curated', riskCeiling: 'T1', requireSignatures: true,
    killSwitch: [] as string[], allowedPublishers: [], allowedCategories: [],
    networkAllowlist: [], enabledSources: ['bundled', 'org', 'peer'],
  },
  anchor: { epoch: 3, fingerprints: ['a24fafdbac6e'] },
  policy: { signatureStatus: 'unsigned', warning: null, epoch: 0, signerFingerprint: null, expiresAt: null },
  pending: [{
    id: 'pub-1', pluginId: 'widget-one', version: '1.0.0', publisher: 'agent-desk',
    submittedAt: '2026-11-15T12:00:00Z', changelog: 'Adds the first widget.',
  }],
  revoked: [],
  inventory: [],
  catalogSource: 'bundled',
  auditEvents: 4,
};

describe('the marketplace says every wait (spec 027)', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState({}, '', '/marketplace');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    window.localStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('turns an expired session into the session notice, not an empty list and a futile retry', async () => {
    window.history.replaceState({}, '', '/marketplace/installed');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ error: 'auth:required' }, 401)));
    render(<MarketplaceApp />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Session required');
    expect(alert).toHaveTextContent('Open Agent Desk from its shortcut to get a fresh link.');
    expect(screen.getByRole('heading', { level: 1, name: 'Session required' })).toHaveFocus();
    // The page's own "did not load" panel never appears: its Try again would
    // fail the same way and the only fix is a fresh shortcut. The notice
    // offers no button at all, because a reload leads back to the same
    // refusal; the message itself is the next step.
    expect(screen.queryByRole('heading', { name: 'The installed list did not load' })).toBeNull();
    expect(within(alert).queryByRole('button')).toBeNull();
    expect(within(alert).getByText('Open Agent Desk from its shortcut to get a fresh link.'))
      .toBeInTheDocument();
  });

  it('holds the describe probe under 100 ms, then shows the control working and ignores a second press', async () => {
    vi.useFakeTimers();
    const availability = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/wizard/availability')) return availability.promise;
      return jsonResponse(catalog());
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MarketplaceApp />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const button = screen.getByRole('button', { name: 'Describe a plugin in plain English' });
    const form = button.closest('form') as HTMLFormElement;

    act(() => { fireEvent.submit(form); });

    // Nothing shows before the gate, but the press cannot fire twice.
    expect(button).not.toHaveAttribute('aria-busy');
    expect(button).toBeDisabled();
    act(() => { vi.advanceTimersByTime(99); });
    expect(button).not.toHaveAttribute('aria-busy');
    act(() => { vi.advanceTimersByTime(1); });
    const pending = screen.getByRole('button', { name: 'Checking the AI connection…' });
    expect(pending).toHaveAttribute('aria-busy', 'true');
    expect(pending).toBeDisabled();

    const probes = fetchMock.mock.calls.filter((call) => String(call[0]).includes('/api/wizard/availability'));
    expect(probes).toHaveLength(1);
  });

  it('shows installed plugins as list-shaped placeholder cards, not one line', async () => {
    window.history.replaceState({}, '', '/marketplace/installed');
    const listing = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async () => listing.promise));
    const { container } = render(<MarketplaceApp />);

    expect(await screen.findByText('Reading installed plugins…')).toBeInTheDocument();
    const busy = container.querySelector('.mkt-installed-skeleton');
    expect(busy).toHaveAttribute('aria-busy', 'true');
    expect(container.querySelectorAll('.mkt-installed-skel')).toHaveLength(2);
    expect(container.querySelector('.mkt-skel')).not.toBeNull();

    await act(async () => { listing.release(jsonResponse(installedResponse([installed()]))); });
    expect(await screen.findByRole('heading', { level: 2, name: 'AR Aging' })).toBeInTheDocument();
    expect(container.querySelector('.mkt-installed-skeleton')).toBeNull();
  });

  it('labels the installed row action and marks the row busy while it runs', async () => {
    window.history.replaceState({}, '', '/marketplace/installed');
    const disable = deferred<Response>();
    let record = installed({ shared: true });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/disable')) return disable.promise;
      if (init?.method === 'POST') return jsonResponse({ id: 'ar-aging', state: 'enabled' });
      return jsonResponse(installedResponse([record]));
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'AR Aging' });
    await user.click(screen.getByRole('button', { name: 'Disable' }));

    const pending = await screen.findByRole('button', { name: 'Disabling…' });
    await waitFor(() => expect(pending).toHaveAttribute('aria-busy', 'true'));
    expect(pending).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Stop sharing' })).toBeDisabled();
    const article = pending.closest('article') as HTMLElement;
    expect(article).toHaveAttribute('aria-busy', 'true');

    record = installed({ enabled: false, shared: true });
    await act(async () => { disable.release(jsonResponse({ id: 'ar-aging', state: 'disabled' })); });
    expect(await screen.findByText('AR Aging is now disabled.')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Enable' })).toBeEnabled();
  });

  it('keeps the rollback dialog open with its button working until the rollback lands', async () => {
    window.history.replaceState({}, '', '/marketplace/installed');
    window.localStorage.clear();
    const rollback = deferred<Response>();
    let rolled = false;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/rollback')) return rollback.promise;
      return jsonResponse(installedResponse([installed({ pinned: { version: rolled ? '1.1.0' : '1.2.0', sha256: 'a'.repeat(64) } })]));
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'AR Aging' });
    await user.click(screen.getByRole('button', { name: 'Roll back' }));
    const dialog = screen.getByRole('dialog', { name: 'Roll back AR Aging' });
    await user.click(within(dialog).getByRole('button', { name: 'Roll back' }));

    const pending = await within(dialog).findByRole('button', { name: 'Rolling back…' });
    await waitFor(() => expect(pending).toHaveAttribute('aria-busy', 'true'));
    expect(pending).toBeDisabled();
    expect(screen.getByRole('dialog', { name: 'Roll back AR Aging' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Roll back' })).toBeDisabled();

    rolled = true;
    await act(async () => { rollback.release(jsonResponse({ id: 'ar-aging', from: '1.2.0', to: '1.1.0' })); });
    expect(await screen.findByText('Rolled back AR Aging from 1.2.0 to 1.1.0.')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('shows the signed-policy import working and a diff-shaped placeholder while it verifies', async () => {
    window.history.replaceState({}, '', '/marketplace/admin');
    const verify = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/policy/import')) return verify.promise;
      return jsonResponse(ADMIN);
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'Import a signed policy' });
    const field = screen.getByLabelText('Signed policy bundle file');
    const file = new File([JSON.stringify({ schemaVersion: 1, policy: {} })], 'policy.json',
      { type: 'application/json' });
    await user.upload(field, file);

    expect(await screen.findByText('Reading and verifying the signed bundle…')).toBeInTheDocument();
    const input = screen.getByLabelText('Signed policy bundle file');
    expect(input).toBeDisabled();
    expect(input).toHaveAttribute('aria-busy', 'true');
    const region = screen.getByRole('region', { name: 'Import a signed policy' });
    expect(region).toHaveAttribute('aria-busy', 'true');
    expect(region.querySelector('.mkt-import-skel')).not.toBeNull();

    await act(async () => {
      verify.release(jsonResponse({
        diff: [{ field: 'mode', before: 'curated', after: 'open' }],
        verification: { signatureStatus: 'signed', warning: null, epoch: 2, signerFingerprint: 'deadbeef', expiresAt: null },
        applied: false,
      }));
    });
    expect(await screen.findByText('Changes in this bundle')).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'open' })).toBeInTheDocument();
    expect(screen.queryByText('Reading and verifying the signed bundle…')).toBeNull();
    expect(screen.getByLabelText('Signed policy bundle file')).toBeEnabled();
  });

  it('names the admin approval and the kill-switch action while they run', async () => {
    window.history.replaceState({}, '', '/marketplace/admin');
    const approve = deferred<Response>();
    const block = deferred<Response>();
    const restore = deferred<Response>();
    let blocked = false;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/approve')) return approve.promise;
      if (init?.method === 'POST' && url.endsWith('/kill-switch')) {
        const body = JSON.parse(String(init.body)) as { enabled: boolean };
        return body.enabled ? block.promise : restore.promise;
      }
      return jsonResponse(blocked
        ? { ...ADMIN, pending: [], posture: { ...ADMIN.posture, killSwitch: ['widget-one'] } }
        : ADMIN);
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'Pending publications' });
    await user.click(screen.getByRole('button', { name: 'Approve widget-one' }));
    const approving = await screen.findByRole('button', { name: 'Approving…' });
    await waitFor(() => expect(approving).toHaveAttribute('aria-busy', 'true'));
    expect(approving).toBeDisabled();
    await act(async () => { approve.release(jsonResponse({ ok: true, id: 'pub-1', decision: 'approve' })); });
    expect(await screen.findByText('Approved widget-one. It is now in the organization catalog.')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Plugin id to block'), 'widget-one');
    const blockButton = screen.getByRole('button', { name: 'Block plugin' });
    await user.click(blockButton);
    const blocking = await screen.findByRole('button', { name: 'Blocking…' });
    await waitFor(() => expect(blocking).toHaveAttribute('aria-busy', 'true'));
    blocked = true;
    await act(async () => { block.release(jsonResponse({ ok: true, pluginId: 'widget-one', enabled: true })); });
    expect(await screen.findByText('widget-one is blocked. It is not eligible to run.')).toBeInTheDocument();

    const restoreButton = await screen.findByRole('button', { name: 'Restore widget-one' });
    await user.click(restoreButton);
    const restoring = await screen.findByRole('button', { name: 'Restoring…' });
    await waitFor(() => expect(restoring).toHaveAttribute('aria-busy', 'true'));
    await act(async () => { restore.release(jsonResponse({ ok: true, pluginId: 'widget-one', enabled: false })); });
  });

  it('shows the admin snapshot as panels of placeholder while it loads', async () => {
    window.history.replaceState({}, '', '/marketplace/admin');
    const snapshot = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async () => snapshot.promise));
    const { container } = render(<MarketplaceApp />);

    expect(await screen.findByText('Reading the governance snapshot…')).toBeInTheDocument();
    const region = container.querySelector('.mkt-skeleton-region') as HTMLElement;
    expect(region).toHaveAttribute('aria-busy', 'true');
    expect(region.querySelectorAll('.mkt-panel-skel').length).toBeGreaterThan(1);

    await act(async () => { snapshot.release(jsonResponse(ADMIN)); });
    expect(await screen.findByRole('heading', { level: 2, name: 'Posture' })).toBeInTheDocument();
  });

  it('keeps the catalog results dimmed and busy while a filter refetches, then swaps them in place', async () => {
    const refetch = deferred<Response>();
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (!url.includes('/api/marketplace/catalog')) return jsonResponse({});
      calls += 1;
      if (calls === 1) return jsonResponse(catalog([card()]));
      return refetch.promise;
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    expect(await screen.findByText('AR Aging')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Source'), 'peer');

    const results = await waitFor(() => {
      const region = document.querySelector('.mkt-results') as HTMLElement;
      expect(region).toHaveAttribute('aria-busy', 'true');
      return region;
    });
    expect(within(results).getByText('AR Aging')).toBeInTheDocument();
    expect(within(results).getByText('Updating the results…')).toBeInTheDocument();
    expect(results).toHaveClass('mkt-refetching');
    expect(document.querySelector('.mkt-grid-skeleton')).toBeNull();

    await act(async () => {
      refetch.release(jsonResponse(catalog([card({ id: 'desk-snapshot', name: 'Desk snapshot' })])));
    });
    expect(await screen.findByText('Desk snapshot')).toBeInTheDocument();
    expect(screen.queryByText('AR Aging')).toBeNull();
    const settled = document.querySelector('.mkt-results') as HTMLElement;
    expect(settled).not.toHaveAttribute('aria-busy');
    expect(settled).not.toHaveClass('mkt-refetching');
  });

  it('disables Search and names it while the searched catalog reloads', async () => {
    const searched = deferred<Response>();
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (!url.includes('/api/marketplace/catalog')) return jsonResponse({});
      calls += 1;
      if (calls === 1) return jsonResponse(catalog([card()]));
      return searched.promise;
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    await screen.findByText('AR Aging');

    await user.type(screen.getByLabelText('Search plugins'), 'aging');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    const pending = await screen.findByRole('button', { name: 'Searching…' });
    await waitFor(() => expect(pending).toHaveAttribute('aria-busy', 'true'));
    expect(pending).toBeDisabled();

    await act(async () => {
      searched.release(jsonResponse(catalog([card({ name: 'Aging report' })])));
    });
    expect(await screen.findByText('Aging report')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Search' })).toBeEnabled();
  });

  it('re-runs the search when the same unchanged query is submitted again', async () => {
    vi.useFakeTimers();
    window.history.replaceState({}, '', '/marketplace/search?q=watch');
    const second = deferred<Response>();
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (!url.includes('/api/marketplace/catalog')) return jsonResponse({});
      calls += 1;
      if (calls === 1) return jsonResponse(catalog([card({ name: 'Competitor Watch' })]));
      return second.promise;
    }));
    render(<MarketplaceApp />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText('Competitor Watch')).toBeInTheDocument();
    expect(calls).toBe(1);

    const button = screen.getByRole('button', { name: 'Search' });
    act(() => { fireEvent.submit(button.closest('form') as HTMLFormElement); });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });

    // The same address still starts a second catalog read, with the old
    // results kept and dimmed.
    expect(calls).toBe(2);
    expect(screen.getByText('Competitor Watch')).toBeInTheDocument();
    const results = document.querySelector('.mkt-results') as HTMLElement;
    expect(results).toHaveClass('mkt-refetching');
    expect(results).toHaveAttribute('aria-busy', 'true');

    // Nothing shows before the 100 ms gate, but the press cannot repeat.
    expect(button).toBeDisabled();
    expect(button).not.toHaveAttribute('aria-busy');
    act(() => { vi.advanceTimersByTime(99); });
    expect(button).not.toHaveAttribute('aria-busy');
    act(() => { vi.advanceTimersByTime(1); });
    const pending = screen.getByRole('button', { name: 'Searching…' });
    expect(pending).toHaveAttribute('aria-busy', 'true');

    await act(async () => {
      second.release(jsonResponse(catalog([card({ name: 'Aging report' })])));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText('Aging report')).toBeInTheDocument();
    expect(screen.queryByText('Competitor Watch')).toBeNull();
  });

  it('re-runs the unfiltered catalog when Discover is submitted empty', async () => {
    vi.useFakeTimers();
    window.history.replaceState({}, '', '/marketplace');
    const second = deferred<Response>();
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (!url.includes('/api/marketplace/catalog')) return jsonResponse({});
      calls += 1;
      if (calls === 1) return jsonResponse(catalog([card()]));
      return second.promise;
    }));
    render(<MarketplaceApp />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText('AR Aging')).toBeInTheDocument();
    expect(calls).toBe(1);

    const button = screen.getByRole('button', { name: 'Search' });
    act(() => { fireEvent.submit(button.closest('form') as HTMLFormElement); });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(calls).toBe(2);
    expect(screen.getByText('AR Aging')).toBeInTheDocument();

    await act(async () => {
      second.release(jsonResponse(catalog([card({ name: 'Desk snapshot' })])));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText('Desk snapshot')).toBeInTheDocument();
  });

  it('names each plugin detail lifecycle action while it runs', async () => {
    window.history.replaceState({}, '', '/marketplace/plugin/ar-aging');
    const enable = deferred<Response>();
    const retest = deferred<Response>();
    let enabled = false;
    let validated = false;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/enable')) return enable.promise;
      if (init?.method === 'POST' && url.endsWith('/retest')) return retest.promise;
      return jsonResponse(detailResponse({
        installed: installed({ enabled }),
        plugin: detail(validated
          ? { validation: { checkedAt: '2026-11-24T10:00:00Z', ok: true, failures: [] } }
          : {}),
      }));
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 1, name: 'AR Aging' });
    await user.click(screen.getByRole('button', { name: 'Enable' }));
    const enabling = await screen.findByRole('button', { name: 'Enabling…' });
    await waitFor(() => expect(enabling).toHaveAttribute('aria-busy', 'true'));
    expect(enabling).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Re-test' })).toBeDisabled();
    enabled = true;
    await act(async () => { enable.release(jsonResponse({ id: 'ar-aging', state: 'enabled' })); });
    expect(await screen.findByText('AR Aging is now enabled.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Re-test' }));
    const retesting = await screen.findByRole('button', { name: 'Re-testing…' });
    await waitFor(() => expect(retesting).toHaveAttribute('aria-busy', 'true'));
    validated = true;
    await act(async () => { retest.release(jsonResponse({ id: 'ar-aging', status: 'ok' })); });
    expect(await screen.findByText('Re-test finished. Validation status refreshed.')).toBeInTheDocument();
  });

  it('shows the manage view a same-shape placeholder while the instances load', async () => {
    window.history.replaceState({}, '', '/marketplace/plugin/qbr-pack/manage');
    const listing = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/instances')) return listing.promise;
      return jsonResponse(detailResponse({
        plugin: detail({ id: 'qbr-pack', name: 'QBR pack' }),
        installed: installed({ id: 'qbr-pack', name: 'QBR pack' }),
      }));
    }));
    render(<MarketplaceApp />);

    const section = await screen.findByRole('region', { name: 'Instances' });
    expect(section).toHaveAttribute('aria-busy', 'true');
    expect(within(section).getByText("Reading this plugin's instances…")).toBeInTheDocument();
    expect(section.querySelectorAll('.mkt-skel').length).toBeGreaterThan(0);

    await act(async () => {
      listing.release(jsonResponse({
        pluginId: 'qbr-pack', configBacked: true, aliasOf: null,
        setupPluginId: 'qbr-pack', setupPluginName: 'QBR pack',
        instances: [{
          schemaVersion: 1, instanceId: 'pipeline', name: 'Pipeline',
          source: { kind: 'workbook', path: '/workspace/q4.xlsx', sheet: null, headerRow: 1, range: null },
          tracking: { labelColumn: 'Region', valueColumn: 'Booked', aggregate: 'sum' },
          confirmedAt: '2026-11-17T10:00:00', suggested: false,
        }],
      }));
    });
    expect(await within(section).findByRole('rowheader', { name: 'Pipeline' })).toBeInTheDocument();
    expect(section).not.toHaveAttribute('aria-busy');
    expect(within(section).queryByText("Reading this plugin's instances…")).toBeNull();
  });

  it('names the Studio start-from copy while it loads the chosen plugin', async () => {
    window.history.replaceState({}, '', '/marketplace/studio');
    const chosen = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/marketplace/plugin/ar-aging')) return chosen.promise;
      return jsonResponse(installedResponse([installed()]));
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 1, name: 'Plugin Studio' });
    const select = await screen.findByLabelText('Installed plugin or blank template');
    await waitFor(() => expect(select).toBeEnabled());
    await user.selectOptions(select, 'ar-aging');

    const busy = await screen.findByRole('status');
    expect(busy).toHaveTextContent('Copying the fields from AR Aging…');
    expect(select).toBeDisabled();
    expect(select).toHaveAttribute('aria-busy', 'true');

    await act(async () => { chosen.release(jsonResponse({ plugin: detail() })); });
    expect(await screen.findByDisplayValue('AR Aging')).toBeInTheDocument();
    expect(await screen.findByText(/Descriptive fields copied/)).toBeInTheDocument();
    expect(screen.getByLabelText('Installed plugin or blank template')).toBeEnabled();
  });

  it('shows the trust center as panels of placeholder, not one line on a blank page', async () => {
    window.history.replaceState({}, '', '/marketplace/trust');
    const snapshot = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async () => snapshot.promise));
    const { container } = render(<MarketplaceApp />);

    expect(await screen.findByText('Reading the trust snapshot…')).toBeInTheDocument();
    const region = container.querySelector('.mkt-skeleton-region') as HTMLElement;
    expect(region).toHaveAttribute('aria-busy', 'true');
    expect(region.querySelectorAll('.mkt-panel-skel').length).toBeGreaterThan(1);

    await act(async () => { snapshot.release(jsonResponse(TRUST)); });
    expect(await screen.findByRole('heading', { level: 2, name: 'Anchor' })).toBeInTheDocument();
    expect(container.querySelector('.mkt-skeleton-region')).toBeNull();
  });

  it('keeps the trust retry on screen, disabled, while it retries', async () => {
    window.history.replaceState({}, '', '/marketplace/trust');
    const retry = deferred<Response>();
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls += 1;
      if (calls === 1) return jsonResponse({ error: 'boom' }, 500);
      return retry.promise;
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { name: 'The trust snapshot could not be loaded' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    const pending = await screen.findByRole('button', { name: 'Trying again…' });
    await waitFor(() => expect(pending).toHaveAttribute('aria-busy', 'true'));
    expect(pending).toBeDisabled();

    await act(async () => { retry.release(jsonResponse(TRUST)); });
    expect(await screen.findByRole('heading', { level: 2, name: 'Anchor' })).toBeInTheDocument();
  });

  it('keeps the publishers retry on screen, disabled, while it retries', async () => {
    window.history.replaceState({}, '', '/marketplace/publishers');
    const retry = deferred<Response>();
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls += 1;
      if (calls === 1) return jsonResponse({ error: 'boom' }, 500);
      return retry.promise;
    }));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Publishers' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    const pending = await screen.findByRole('button', { name: 'Trying again…' });
    await waitFor(() => expect(pending).toHaveAttribute('aria-busy', 'true'));
    expect(pending).toBeDisabled();

    await act(async () => { retry.release(jsonResponse(catalog([card()]))); });
    expect(await screen.findByRole('rowheader', { name: 'agent-desk' })).toBeInTheDocument();
  });

  it('shows a publisher a page-shaped placeholder while the id loads', async () => {
    window.history.replaceState({}, '', '/marketplace/publisher/agent-desk');
    const publisher = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(async () => publisher.promise));
    const { container } = render(<MarketplaceApp />);

    expect(await screen.findByText('Reading the publisher…')).toBeInTheDocument();
    const region = container.querySelector('.mkt-skeleton-region') as HTMLElement;
    expect(region).toHaveAttribute('aria-busy', 'true');
    expect(region.querySelector('.mkt-panel-skel')).not.toBeNull();
    expect(region.querySelector('.mkt-grid-skeleton')).not.toBeNull();

    await act(async () => {
      publisher.release(jsonResponse({
        publisher: 'agent-desk', verified: true, proof: 'No proof on file',
        plugins: [card()], firstSeen: '2026-11-01',
      }));
    });
    expect(await screen.findByRole('heading', { level: 1, name: 'agent-desk' })).toBeInTheDocument();
  });

  it('keeps an ineligible row sentence on its own full line', () => {
    // The audit's long-values condition caught this line setting the row's
    // auto column wide and squeezing the summary and publisher beside it.
    expect(marketplaceCss).toContain('.mkt-row .mkt-ineligible { grid-column: 1 / -1; }');
  });
});
