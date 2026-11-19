// A pack install is one sheet and one POST. When the server names a
// blocked member, the page must say so and install nothing.
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { packs } from './marketplace-fixtures';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

describe('pack install', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/marketplace/pack/manager');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, '', '/');
  });

  it('lists every member scope in one sheet and reports the blocked member', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST') {
        expect(url).toBe('/api/marketplace/packs/install');
        expect(JSON.parse(String(init.body))).toEqual({ id: 'manager' });
        return jsonResponse({
          error: 'policy:blocked',
          message: 'Policy blocked filesystem.read for revenue-vs-target.',
          details: { blockedMember: 'revenue-vs-target' },
        }, 403);
      }
      return jsonResponse(packs());
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Manager pack' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Review and install all 2 plugins' }));

    const dialog = screen.getByRole('dialog', { name: 'Install Manager pack' });
    expect(within(dialog).getByText('Reads files matching ${workspace}/finance/**.')).toBeInTheDocument();
    expect(within(dialog).getByText('Reads files matching ${workspace}/sales/**.')).toBeInTheDocument();
    expect(within(dialog).getByText(/This installs 2 plugins together. All or none/)).toBeInTheDocument();
    expect(within(dialog).getByText('It can never read or write files outside the paths listed above.')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Install all 2' }));

    const messages = await screen.findAllByText(/Manager pack was not installed: revenue-vs-target is blocked/);
    expect(messages.length).toBeGreaterThan(0);
    expect(messages.some((node) => node.classList.contains('mkt-error'))).toBe(true);
    expect(screen.queryByText(/Installed 2 plugins from Manager pack./)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter((call) => (call[1] as RequestInit | undefined)?.method === 'POST')).toHaveLength(1);
  });

  it('shows the blocked member before anyone opens the sheet', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(packs([
      {
        ...packs().packs[0],
        eligible: false,
        blockedMember: 'revenue-vs-target',
        blockedReason: 'Policy blocked filesystem.read for revenue-vs-target.',
      },
    ]))));
    render(<MarketplaceApp />);
    expect(await screen.findByText(/is blocked by the current policy/)).toBeInTheDocument();
    expect(screen.getByText('revenue-vs-target')).toBeInTheDocument();
  });

  it('says packs were retired when the marketplace publishes none', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse(packs([])));
    vi.stubGlobal('fetch', fetchMock);
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Packs are no longer offered' }))
      .toBeInTheDocument();
    expect(screen.getByText(/This marketplace stopped publishing packs/)).toBeInTheDocument();
    expect(screen.getByText('Nothing is bundled to install.')).toBeInTheDocument();
    expect(screen.getByText(/The pack set was retired on purpose/)).toBeInTheDocument();
    expect(screen.getByText(/The two plugins this desk still ships are on Discover/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Browse plugins' })).toHaveAttribute('href', '/marketplace');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /install/i })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/marketplace/packs');
    expect(fetchMock.mock.calls.filter((call) => (call[1] as RequestInit | undefined)?.method === 'POST'))
      .toHaveLength(0);
  });

  it('still answers for an unknown pack while packs exist', async () => {
    window.history.replaceState({}, '', '/marketplace/pack/missing');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(packs())));
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Pack not found' })).toBeInTheDocument();
    expect(screen.getByText('No pack has the id “missing”.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
