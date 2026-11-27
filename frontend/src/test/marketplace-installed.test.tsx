// Installed rows are server state: a toggle, an update or a purge posts
// once and the list is re-read. No row flips before the server answers.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { installed, installedResponse } from './marketplace-fixtures';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

describe('installed plugins', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/marketplace/installed');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, '', '/');
  });

  it('renders pinned version, digest, pilot and shared flags, then disables from the response', async () => {
    let record = installed({ shared: true });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST') {
        expect(url).toBe('/api/marketplace/disable');
        expect(JSON.parse(String(init.body))).toEqual({ id: 'ar-aging' });
        record = installed({ enabled: false, status: { status: 'disabled', cause: '', checked_at: '2026-11-02T10:00:00Z' } });
        return jsonResponse({ id: 'ar-aging', state: 'disabled' });
      }
      return jsonResponse(installedResponse([record]));
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Installed plugins' })).toBeInTheDocument();
    expect(screen.getByText('v1.2.0')).toBeInTheDocument();
    expect(screen.getByText('sha256:aaaaaaaaaaaa')).toBeInTheDocument();
    expect(screen.getByText('Pilot: 2 of 3 views left')).toBeInTheDocument();
    expect(screen.getByText('Pilot: 2 of 3 views left'))
      .toHaveAttribute('title', 'Pilot: 2 of 3 views left');
    expect(screen.getByText('Shared')).toBeInTheDocument();
    expect(screen.getByText(/2\.0 KB/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Disable' }));
    expect(await screen.findByText('AR Aging is now disabled.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Enable' })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter((call) => (call[1] as RequestInit | undefined)?.method === 'POST')).toHaveLength(1);
  });

  it('reviews an update, shows the added scope, then accepts the staged consent', async () => {
    let record = installed({
      update: {
        version: '1.3.0', digest: 'sha256:abc',
        widening: ['filesystem.write: ${workspace}/finance/**'],
        dropping: [],
        scopes: ['filesystem.read: ${workspace}/finance/**', 'filesystem.write: ${workspace}/finance/**'],
      },
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/update')) {
        record = installed({
          pendingConsent: true,
          update: {
            version: '1.3.0', digest: 'sha256:abc',
            widening: ['filesystem.write: ${workspace}/finance/**'],
            dropping: [],
            scopes: ['filesystem.read: ${workspace}/finance/**', 'filesystem.write: ${workspace}/finance/**'],
          },
        });
        return jsonResponse({ id: 'ar-aging', from: '1.2.0', to: '1.3.0', pendingConsent: true });
      }
      if (init?.method === 'POST' && url.endsWith('/consent')) {
        expect(JSON.parse(String(init.body))).toEqual({ id: 'ar-aging', decision: 'accept' });
        record = installed({ version: '1.3.0', pinned: { version: '1.3.0', sha256: 'b'.repeat(64) } });
        return jsonResponse({ id: 'ar-aging', version: '1.3.0', status: 'installed' });
      }
      return jsonResponse(installedResponse([record]));
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByText('Update available: v1.3.0.');
    await user.click(screen.getByRole('button', { name: 'Review and update' }));

    const dialog = await screen.findByRole('dialog', { name: 'Review update for AR Aging' });
    expect(within(dialog).getByText('New in this version')).toBeInTheDocument();
    expect(within(dialog).getByText('Writes files matching ${workspace}/finance/**.')).toBeInTheDocument();
    expect(within(dialog).getByText(/This update widens access: 1 new scope marked above./)).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Accept update' }));
    expect(await screen.findByText('AR Aging updated to 1.3.0.')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('reads a held permission drop as a drop, not a widening', async () => {
    const record = installed({
      pendingConsent: true,
      update: {
        version: '1.3.0', digest: 'sha256:abc',
        widening: [],
        dropping: ['llm.allow: True'],
        scopes: ['llm.allow: False'],
      },
    });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(installedResponse([record]))));
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    expect(await screen.findByText('The staged version drops 1 scope.')).toBeInTheDocument();
    expect(screen.queryByText(/adds 1 scope/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Review update' }));
    const dialog = await screen.findByRole('dialog', { name: 'Review update for AR Aging' });
    expect(within(dialog).getByText('It asks for no new data access.')).toBeInTheDocument();
    expect(within(dialog).getByText('The new version drops 1 scope.')).toBeInTheDocument();
    expect(within(dialog).queryByText(/This update widens access/)).not.toBeInTheDocument();
    expect(within(dialog).queryByText('It asks for no data access.')).not.toBeInTheDocument();
  });

  it('requires the typed delete-data confirmation before purging', async () => {
    let purged = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST') {
        expect(url).toBe('/api/marketplace/purge-data');
        expect(JSON.parse(String(init.body))).toEqual({ id: 'ar-aging', confirm: 'delete-data:ar-aging' });
        purged = true;
        return jsonResponse({ ok: true, purged: 'ar-aging' });
      }
      return jsonResponse(installedResponse(purged ? [] : [installed()]));
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await screen.findByRole('heading', { level: 2, name: 'AR Aging' });
    await user.click(screen.getByRole('button', { name: 'Purge data' }));

    const dialog = screen.getByRole('dialog', { name: 'Purge data for AR Aging' });
    const confirm = within(dialog).getByRole('button', { name: 'Purge data' });
    const field = within(dialog).getByLabelText(/Type delete-data:ar-aging to confirm/);
    const phrase = within(dialog).getByText('delete-data:ar-aging');
    expect(phrase.tagName).toBe('CODE');
    expect(phrase).toHaveAttribute('tabindex', '0');
    expect(phrase).toHaveAttribute('title', 'delete-data:ar-aging');
    expect(confirm).toBeDisabled();

    await user.type(field, 'delete-data:ar-agin');
    expect(confirm).toBeDisabled();
    await user.type(field, 'g');
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    expect(await screen.findByText('AR Aging data purged.')).toBeInTheDocument();
    expect(await screen.findByText('Nothing is installed yet.')).toBeInTheDocument();
  });
});
