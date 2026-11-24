// The honest "cannot run on this desk" state: a plugin that asks to reach
// the web cannot run when the plugin runner has no HTTP transport. The
// desk says so without deciding whether the plugin may be installed.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { detail, detailResponse, installed, installedResponse } from './marketplace-fixtures';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

const WEB_CAPABILITIES = {
  sources: ['http-get'],
  permissions: ['network.allow: example.com'],
  elementKinds: ['list'],
  filesystem: [],
  network: ['example.com'],
};

function webPlugin() {
  return detail({
    id: 'competitor-watch',
    name: 'Competitor Watch',
    category: 'research',
    summary: 'Did the competitor pricing page change since the last check?',
    capabilities: WEB_CAPABILITIES,
  });
}

const NOTICE = 'This desk cannot read web pages yet, so this plugin cannot run here.';

function stubDetail(deskNetwork: boolean | undefined) {
  const fetchMock = vi.fn(async () => jsonResponse(
    detailResponse({ plugin: webPlugin(), deskNetwork }),
  ));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('a plugin that asks for the web', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/marketplace/plugin/competitor-watch');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, '', '/');
  });

  it('says it cannot run when the desk has no web access, and leaves Install enabled', async () => {
    stubDetail(false);
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Competitor Watch' })).toBeInTheDocument();
    expect(screen.getByText(NOTICE)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Install plugin' })).toBeEnabled();
  });

  it('also reads an HTTP source as asking for the web', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(detailResponse({
      plugin: detail({
        id: 'competitor-watch', name: 'Competitor Watch',
        capabilities: { ...WEB_CAPABILITIES, network: [] },
      }),
      deskNetwork: false,
    }))));
    render(<MarketplaceApp />);

    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
  });

  it('hides Re-test once installed, because it can never succeed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(detailResponse({
      plugin: webPlugin(),
      installed: installed(),
      deskNetwork: false,
    }))));
    render(<MarketplaceApp />);

    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Re-test' })).not.toBeInTheDocument();
  });

  it('shows no notice when the desk has web access', async () => {
    stubDetail(true);
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 1, name: 'Competitor Watch' });
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
  });

  it('shows no notice when the server does not send the field', async () => {
    stubDetail(undefined);
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 1, name: 'Competitor Watch' });
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
  });
});

describe('an installed plugin that cannot run', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/marketplace/installed');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, '', '/');
  });

  function stubInstalled(deskNetwork: boolean | undefined, capabilities = WEB_CAPABILITIES) {
    const urls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url === '/api/marketplace/installed') {
        return jsonResponse(installedResponse([
          installed({
            id: 'competitor-watch',
            name: 'Competitor Watch',
            status: { status: 'attention', cause: '', checked_at: '2026-11-01T09:05:00Z' },
          }),
        ], deskNetwork));
      }
      if (url.includes('/api/marketplace/plugin/')) {
        return jsonResponse(detailResponse({
          plugin: detail({
            id: 'competitor-watch',
            name: 'Competitor Watch',
            capabilities,
          }),
          deskNetwork,
        }));
      }
      throw new Error('unexpected request: ' + url);
    });
    vi.stubGlobal('fetch', fetchMock);
    return urls;
  }

  it('shows the state with Remove as the primary action and no Re-test', async () => {
    stubInstalled(false);
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'Competitor Watch' });
    expect(await screen.findByText('Cannot run on this desk')).toBeInTheDocument();
    expect(screen.getByText(NOTICE)).toBeInTheDocument();
    const remove = screen.getByRole('button', { name: 'Remove' });
    expect(remove).toHaveClass('btn-primary');
    expect(screen.queryByRole('button', { name: /Re-test/ })).not.toBeInTheDocument();
    // Remove is the only action: a plugin that cannot run has nothing else
    // to do here.
    const article = screen.getByRole('heading', { level: 2, name: 'Competitor Watch' })
      .closest('article') as HTMLElement;
    expect(within(article).getAllByRole('button').map((button) => button.textContent?.trim()))
      .toEqual(['Remove']);

    const user = userEvent.setup();
    await user.click(remove);
    expect(await screen.findByRole('dialog', { name: 'Uninstall Competitor Watch' })).toBeInTheDocument();
  });

  it('shows no state and reads no detail when the desk has web access', async () => {
    const urls = stubInstalled(true);
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'Competitor Watch' });
    expect(screen.queryByText('Cannot run on this desk')).not.toBeInTheDocument();
    expect(urls.filter((url) => url.includes('/api/marketplace/plugin/'))).toEqual([]);
  });

  it('shows no state and reads no detail when the server omits the field', async () => {
    const urls = stubInstalled(undefined);
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'Competitor Watch' });
    expect(screen.queryByText('Cannot run on this desk')).not.toBeInTheDocument();
    expect(urls.filter((url) => url.includes('/api/marketplace/plugin/'))).toEqual([]);
  });

  it('shows no state when the plugin does not ask for the web', async () => {
    stubInstalled(false, {
      sources: ['excel-watch'], permissions: [], elementKinds: ['metric'], filesystem: [], network: [],
    });
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'Competitor Watch' });
    await waitFor(() => {
      expect(screen.queryByText('Cannot run on this desk')).not.toBeInTheDocument();
    });
  });
});
