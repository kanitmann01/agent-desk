// Plugin detail is a fixed content contract: sample, permissions, proof,
// validator date and version history all have to be on screen. The
// install and update sheets must carry the server's scopes, not a guess.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { detailResponse, installed } from './marketplace-fixtures';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

function stubDetail(data: ReturnType<typeof detailResponse>, post: Record<string, unknown> = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body ?? '{}')) as { id?: string };
      const path = url.replace('/api/marketplace/', '');
      return jsonResponse(post[path] ?? { id: body.id, version: '1.2.0', status: 'ok' });
    }
    if (url.includes('/api/marketplace/plugin/')) return jsonResponse(data);
    return jsonResponse({});
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('plugin detail', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/marketplace/plugin/ar-aging');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, '', '/');
  });

  it('renders sample, permissions, can-never list, proof, validator date and version headers', async () => {
    stubDetail(detailResponse());
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'AR Aging' })).toBeInTheDocument();
    expect(screen.getAllByText('Sample data').length).toBeGreaterThan(0);
    expect(screen.getByText('Overdue invoices')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('Largest balance: Meridian, 41 days late.')).toBeInTheDocument();

    expect(screen.getByText('Reads files matching ${workspace}/finance/**.')).toBeInTheDocument();
    expect(screen.getByText('You control this under Files and folders.')).toBeInTheDocument();
    expect(screen.getByText('It can never open a network connection.')).toBeInTheDocument();
    expect(screen.getByText('It can never run shell commands or start another program.')).toBeInTheDocument();

    expect(screen.getByText('SHA256:feedfacefeedfacefeedfacefeedface')).toBeInTheDocument();
    expect(screen.getByText(/Checked Nov 1, 2026/)).toBeInTheDocument();

    const facts = screen.getByRole('region', { name: 'Plugin facts' });
    const publisherValue = within(facts).getByText('agent-desk');
    expect(publisherValue).toHaveAttribute('tabindex', '0');
    expect(publisherValue).toHaveAttribute('title', 'agent-desk');
    const digestCode = within(facts).getByTitle(detailResponse().plugin.digest);
    expect(digestCode.tagName).toBe('CODE');
    expect(digestCode).toHaveAttribute('tabindex', '0');
    expect(screen.getByText('Adds a days-late column and a largest-balance line.')).toBeInTheDocument();

    const table = screen.getByRole('table', { name: /Versions of AR Aging/ });
    for (const header of ['Version', 'Digest', 'Change', 'Status']) {
      expect(within(table).getByRole('columnheader', { name: header })).toBeInTheDocument();
    }
    expect(within(table).getByRole('rowheader', { name: 'v1.2.0' })).toBeInTheDocument();
  });

  it('opens a consent sheet for a fresh install, then posts id and version', async () => {
    const fetchMock = stubDetail(detailResponse(), {
      install: { id: 'ar-aging', version: '1.2.0', scopes: [], widening: [], status: 'installed' },
    });
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'AR Aging' });

    await user.click(screen.getByRole('button', { name: 'Install plugin' }));
    const dialog = screen.getByRole('dialog', { name: 'Install AR Aging' });
    expect(within(dialog).getByText('Reads files matching ${workspace}/finance/**.')).toBeInTheDocument();
    expect(within(dialog).getByText('It can never open a network connection.')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Install plugin' }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((call) => (call[1] as RequestInit | undefined)?.method === 'POST');
      expect(post).toBeTruthy();
      expect(String(post?.[0])).toBe('/api/marketplace/install');
      expect(JSON.parse(String((post?.[1] as RequestInit).body))).toEqual({ id: 'ar-aging', version: '1.2.0' });
    });
    expect(await screen.findByText('Installed AR Aging 1.2.0.')).toBeInTheDocument();
  });

  it('marks the widened scopes when a staged update needs consent', async () => {
    const base = installed();
    stubDetail(detailResponse({
      installed: {
        ...base,
        update: {
          version: '1.3.0',
          digest: 'sha256:abc',
          widening: ['filesystem.write: ${workspace}/finance/**'],
          dropping: [],
          scopes: [
            'filesystem.read: ${workspace}/finance/**',
            'filesystem.write: ${workspace}/finance/**',
          ],
        },
      },
    }), { update: { id: 'ar-aging', from: '1.2.0', to: '1.3.0', pendingConsent: false } });
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'AR Aging' });

    await user.click(screen.getByRole('button', { name: 'Update to 1.3.0' }));
    const dialog = screen.getByRole('dialog', { name: 'Update AR Aging' });
    expect(within(dialog).getByText('Reads files matching ${workspace}/finance/**.')).toBeInTheDocument();
    expect(within(dialog).getByText('Writes files matching ${workspace}/finance/**.')).toBeInTheDocument();
    expect(within(dialog).getByText('New in this version')).toBeInTheDocument();
    expect(within(dialog).getByText(/This update widens access: 1 new scope marked above./)).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Update plugin' }));
    expect(await screen.findByText('Updated to 1.3.0.')).toBeInTheDocument();
  });
});
