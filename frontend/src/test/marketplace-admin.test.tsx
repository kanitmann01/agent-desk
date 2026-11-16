// The admin surface is a read-mostly view of the signed policy. The import
// flow must show a diff first and only write after a second confirmation.
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

function adminSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    posture: {
      mode: 'curated',
      riskCeiling: 'T1',
      requireSignatures: true,
      killSwitch: [] as string[],
      allowedPublishers: [] as string[],
      allowedCategories: [] as string[],
      networkAllowlist: [] as string[],
      enabledSources: ['bundled', 'org', 'peer'],
    },
    anchor: { epoch: 3, fingerprints: ['a24fafdbac6e'] },
    policy: {
      signatureStatus: 'unsigned',
      warning: null as string | null,
      epoch: 0,
      signerFingerprint: null as string | null,
      expiresAt: null as string | null,
    },
    pending: [{
      id: 'pub-1',
      pluginId: 'widget-one',
      version: '1.0.0',
      publisher: 'agent-desk',
      submittedAt: '2026-11-15T12:00:00Z',
      changelog: 'Adds the first widget.',
    }],
    revoked: [] as unknown[],
    inventory: [{
      id: 'widget-one',
      version: '1.0.0',
      publisher: 'agent-desk',
      digest: 'abcdef1234567890abcdef',
      enabled: true,
      eligible: true,
      reasons: [] as unknown[],
    }],
    catalogSource: 'bundled',
    auditEvents: 4,
    ...overrides,
  };
}

describe('Marketplace admin', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/marketplace/admin');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, '', '/');
  });

  it('renders posture, anchor, pending work and inventory, then approves', async () => {
    const requests: { url: string; method: string; body: unknown }[] = [];
    let approved = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      requests.push({
        url,
        method,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      if (url.endsWith('/api/marketplace/admin')) {
        return jsonResponse(adminSnapshot(approved ? { pending: [] } : {}));
      }
      if (url.endsWith('/api/marketplace/admin/publications/pub-1/approve')) {
        approved = true;
        return jsonResponse({ ok: true, id: 'pub-1', decision: 'approve', pluginId: 'widget-one' });
      }
      throw new Error('unexpected request: ' + method + ' ' + url);
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Marketplace admin' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Posture' })).toBeInTheDocument();
    expect(screen.getByText('curated')).toBeInTheDocument();
    expect(screen.getByText('a24fafdbac6e')).toBeInTheDocument();
    expect(screen.getByText('Adds the first widget.')).toBeInTheDocument();
    expect(screen.getByText('abcdef123456')).toBeInTheDocument();
    expect(screen.getAllByText('widget-one').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Approve widget-one' }));

    await waitFor(() => {
      expect(requests.some((request) =>
        request.method === 'POST'
        && request.url.endsWith('/api/marketplace/admin/publications/pub-1/approve'))).toBe(true);
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Approved widget-one.');
  });

  it('shows the bundle diff first, then applies only after the second click', async () => {
    const requests: { url: string; method: string; body: unknown }[] = [];
    let imported = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : null;
      requests.push({ url, method, body });
      if (url.endsWith('/api/marketplace/admin')) {
        return jsonResponse(adminSnapshot(imported ? {
          policy: {
            signatureStatus: 'signed',
            warning: null,
            epoch: 2,
            signerFingerprint: 'deadbeef',
            expiresAt: '2027-11-15T12:00:00Z',
          },
          pending: [],
        } : {}));
      }
      if (url.endsWith('/api/marketplace/policy/import')) {
        const verification = {
          signatureStatus: 'signed',
          warning: null as string | null,
          epoch: 2,
          signerFingerprint: 'deadbeef',
          expiresAt: '2027-11-15T12:00:00Z',
        };
        if (body?.confirm === true) {
          imported = true;
          return jsonResponse({ diff: [], verification, applied: true });
        }
        expect(body?.confirm).toBe(false);
        return jsonResponse({
          diff: [
            { field: 'allowedPublishers', before: [], after: ['acme', 'zeta'] },
            { field: 'mode', before: 'curated', after: 'open' },
          ],
          verification,
          applied: false,
        });
      }
      throw new Error('unexpected request: ' + method + ' ' + url);
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Marketplace admin' })).toBeInTheDocument();
    const file = new File([JSON.stringify({ schemaVersion: 1, policy: {} })], 'policy.json', {
      type: 'application/json',
    });
    await user.upload(screen.getByLabelText('Signed policy bundle file'), file);

    expect(await screen.findByText('Changes in this bundle')).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'open' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'acme, zeta' })).toBeInTheDocument();
    expect(requests.some((request) => request.body && (request.body as { confirm?: boolean }).confirm === true))
      .toBe(false);

    await user.click(screen.getByRole('button', { name: 'Apply signed policy' }));

    await waitFor(() => {
      expect(requests.some((request) =>
        request.url.endsWith('/api/marketplace/policy/import')
        && (request.body as { confirm?: boolean } | null)?.confirm === true)).toBe(true);
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Signed policy applied.');
    expect(imported).toBe(true);
  });

  it('explains that admin mode is off instead of crashing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({
      error: 'admin:disabled',
      message: 'the marketplace admin surface is disabled; set AGENTDESK_MARKETPLACE_ADMIN=1 and reload the server',
      details: { env: 'AGENTDESK_MARKETPLACE_ADMIN' },
    }, 403)));
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Marketplace admin' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Admin mode is off' })).toBeInTheDocument();
    expect(screen.getByText(/AGENTDESK_MARKETPLACE_ADMIN=1/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Posture' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Apply signed policy/ })).not.toBeInTheDocument();
  });
});
