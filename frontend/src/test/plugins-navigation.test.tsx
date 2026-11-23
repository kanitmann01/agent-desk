// R25 (spec 022): the Plugins page offers two sections and nothing else,
// and Find plugins is where the plain-English wizard starts. Publishers,
// Studio, Admin and the Trust center keep their addresses and lose their
// links, so a person managing plugins has two places to look.
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import Rail from '../dashboard/Rail';
import { catalog } from './marketplace-fixtures';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

const ADMIN_ONLY = [
  '/marketplace/publishers',
  '/marketplace/publisher',
  '/marketplace/studio',
  '/marketplace/admin',
  '/marketplace/trust',
];

/** Every address the rendered document links to. */
function linkedHrefs(): string[] {
  return Array.from(document.querySelectorAll('a[href]')).map((a) => a.getAttribute('href') ?? '');
}

describe('the Plugins page navigation (R25)', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState({}, '', '/marketplace');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(catalog())));
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('offers exactly Find plugins and Installed', async () => {
    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'Find plugins' });
    const nav = screen.getByRole('navigation', { name: 'Plugins sections' });
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual(['Find plugins', 'Installed']);
    expect(within(nav).getByRole('link', { name: 'Find plugins' })).toHaveAttribute('href', '/marketplace');
    expect(within(nav).getByRole('link', { name: 'Find plugins' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('link', { name: 'Installed' })).toHaveAttribute('href', '/marketplace/installed');
  });

  it('links nowhere to Publishers, Studio, Admin or the Trust center', async () => {
    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'Find plugins' });
    const hrefs = linkedHrefs();
    for (const path of ADMIN_ONLY) {
      expect(hrefs.filter((href) => href === path || href.startsWith(`${path}/`))).toEqual([]);
    }
    for (const retired of ['Publishers', 'Studio', 'Admin', 'Trust center']) {
      expect(screen.queryByRole('link', { name: retired })).toBeNull();
    }
  });

  it('starts the plain-English wizard from Find plugins', async () => {
    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'Find plugins' });
    const button = screen.getByRole('button', { name: 'Describe a plugin in plain English' });
    // The wizard is a server-rendered walk: a plain form post, no script.
    const form = button.closest('form');
    expect(form).not.toBeNull();
    expect(form).toHaveAttribute('method', 'post');
    expect(form).toHaveAttribute('action', '/wizard/start');
  });

  it('leaves the wizard off search results and category pages', async () => {
    window.history.replaceState({}, '', '/marketplace/search?q=aging');
    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'Search results' });
    expect(screen.queryByRole('button', { name: 'Describe a plugin in plain English' })).toBeNull();
    // Results belong to Find plugins, so that tab stays marked.
    expect(screen.getByRole('link', { name: 'Find plugins' })).toHaveAttribute('aria-current', 'page');
  });

  it('still opens the admin-only pages by address, without offering a way back to them', async () => {
    window.history.replaceState({}, '', '/marketplace/trust');
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({})));
    render(<MarketplaceApp />);
    expect(screen.getByRole('navigation', { name: 'Plugins sections' })).toBeInTheDocument();
    expect(linkedHrefs().filter((href) => ADMIN_ONLY.some((path) => href.startsWith(path)))).toEqual([]);
  });

  it('names the entry Plugins in the rail', () => {
    render(<Rail inboxWaiting={0} active="/marketplace" />);
    expect(screen.getByRole('link', { name: 'Plugins' })).toHaveAttribute('href', '/marketplace');
    expect(screen.getByRole('link', { name: 'Plugins' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('link', { name: 'Marketplace' })).toBeNull();
    // The visible label says it too: the rail entry and the phone bar.
    expect(screen.getAllByText('Plugins').length).toBeGreaterThan(0);
  });
});
