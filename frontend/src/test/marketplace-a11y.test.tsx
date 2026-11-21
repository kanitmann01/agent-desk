// Keyboard access on the marketplace: the skip link comes first, the
// current route is exposed with aria-current (not colour alone), and the
// consent sheet traps Tab, closes on Escape and returns focus. The
// destructive dialogs (uninstall, rollback, purge) carry the same focus
// contract via the shared hook the consent sheet implements.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { catalog, detailResponse, installedResponse } from './marketplace-fixtures';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

function stubCatalog(): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async () => jsonResponse(catalog()));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function stubDetail(data = detailResponse()): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === 'POST') {
      return jsonResponse({ id: 'ar-aging', version: '1.2.0', status: 'installed' });
    }
    if (url.includes('/api/marketplace/plugin/')) return jsonResponse(data);
    return jsonResponse({});
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('marketplace keyboard access', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState({}, '', '/marketplace');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('puts a skip link first and marks the active tab and rail entry', async () => {
    stubCatalog();
    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'Discover plugins' });

    const skip = screen.getByRole('link', { name: 'Skip to main content' });
    expect(skip).toHaveAttribute('href', '#marketplace-main');
    expect(skip.parentElement?.firstElementChild).toBe(skip);
    skip.focus();
    expect(skip).toHaveFocus();

    expect(screen.getByRole('link', { name: 'Discover' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Installed' })).not.toHaveAttribute('aria-current');
    expect(screen.getByRole('link', { name: 'Marketplace' })).toHaveAttribute('aria-current', 'page');
  });

  it('traps Tab in the consent sheet, closes on Escape and restores focus', async () => {
    window.history.replaceState({}, '', '/marketplace/plugin/ar-aging');
    stubDetail();
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'AR Aging' });

    const trigger = screen.getByRole('button', { name: 'Install plugin' });
    await user.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Install AR Aging' });
    const close = within(dialog).getByRole('button', { name: 'Close permission review' });
    const confirm = within(dialog).getByRole('button', { name: 'Install plugin' });
    await waitFor(() => expect(close).toHaveFocus());

    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab();
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await user.tab({ shift: true });
    expect(close).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('gives the uninstall dialog the consent sheet focus contract', async () => {
    window.history.replaceState({}, '', '/marketplace/installed');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(installedResponse())));
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'Installed plugins' });

    const trigger = screen.getByRole('button', { name: 'Uninstall' });
    await user.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Uninstall AR Aging' });
    // Focus moves into the dialog, onto its first control.
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    const confirm = within(dialog).getByRole('button', { name: 'Uninstall' });
    await waitFor(() => expect(cancel).toHaveFocus());

    // Tab cycles inside the dialog and wraps at both ends.
    await user.tab();
    expect(confirm).toHaveFocus();
    await user.tab();
    expect(cancel).toHaveFocus();
    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();

    // Escape closes and focus returns to the control that opened it.
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
