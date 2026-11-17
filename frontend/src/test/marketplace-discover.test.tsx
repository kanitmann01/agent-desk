// Discover and Search share one catalog surface. These tests stub the
// server response and assert the card contract, the filters that reach
// the API, and the honest empty/error states.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { card, catalog } from './marketplace-fixtures';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

function stubCatalog(data = catalog()): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async () => jsonResponse(data));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('the marketplace catalog surface', () => {
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

  it('renders the server card contract, including the plain-English ineligible reason', async () => {
    stubCatalog(catalog([
      card(),
      card({
        id: 'desk-snapshot', name: 'Desk snapshot',
        summary: 'A read-only snapshot of the desk, published by a small tools shop.',
        version: '0.3.0', category: 'reference', riskTier: 'high',
        publisher: 'kestra-tools',
        publisherVerified: false, source: 'peer', eligible: false,
        ineligibleReasons: [{
          code: 'signature-required',
          message: 'This plugin is not signed, and the current policy requires a signature.',
        }],
      }),
    ]));
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Discover plugins' })).toBeInTheDocument();
    expect(screen.getByText('AR Aging')).toBeInTheDocument();
    expect(screen.getByText('2 of 2 plugins')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /AR Aging, version 1\.2\.0, agent-desk/ });
    expect(within(link).getByText('Overdue invoices by customer, refreshed from the workbook you already keep.')).toBeInTheDocument();
    expect(within(link).getByText('v1.2.0')).toBeInTheDocument();
    expect(within(link).getByText('Finance')).toBeInTheDocument();
    expect(within(link).getByText('Medium risk')).toBeInTheDocument();
    expect(within(link).queryByText('Bundled')).toBeNull();
    expect(within(link).queryByText('Verified')).toBeNull();

    const reason = screen.getByText(/This plugin is not signed, and the current policy requires a signature./);
    expect(reason.closest('p')).toHaveClass('mkt-ineligible');
    expect(screen.getByText('Not available:')).toBeInTheDocument();
    expect(screen.getByText('Unverified publisher')).toBeInTheDocument();

    expect(link).toHaveAttribute('href', '/marketplace/plugin/ar-aging');
  });

  it('sends every filter to the catalog API instead of filtering a stale list', async () => {
    const fetchMock = stubCatalog();
    const user = userEvent.setup();
    render(<MarketplaceApp />);
    await screen.findByText('AR Aging');

    await user.selectOptions(screen.getByLabelText('Source'), 'peer');
    await user.selectOptions(screen.getByLabelText('Risk'), 'high');
    await user.click(screen.getByLabelText('Only available plugins'));

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(urls.some((url) => url === '/api/marketplace/catalog?source=peer&risk=high&eligible=1')).toBe(true);
    });
  });

  it('renders Search from the q in the URL and asks the API the same question', async () => {
    window.history.replaceState({}, '', '/marketplace/search?q=overdue%20invoices');
    const fetchMock = stubCatalog(catalog([card()]));
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Search results' })).toBeInTheDocument();
    expect(screen.getByText('1 of 1 plugin matching “overdue invoices”')).toBeInTheDocument();
    expect(fetchMock.mock.calls.map((call) => String(call[0])))
      .toContain('/api/marketplace/catalog?q=overdue+invoices');
    await waitFor(() => expect(screen.getByLabelText('Search plugins')).toHaveValue('overdue invoices'));
  });

  it('shows an empty state with a way back when nothing matches', async () => {
    stubCatalog({ ...catalog([]), total: 0, sources: [] });
    render(<MarketplaceApp />);
    expect(await screen.findByText('No plugins match those filters.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument();
    expect(screen.getByText('No plugins')).toBeInTheDocument();
  });

  it('shows the error, then recovers on retry without inventing rows', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(jsonResponse(catalog()));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    const alert = await screen.findByRole('alert');
    expect(within(alert).getByRole('heading', { name: 'The catalog did not load' })).toBeInTheDocument();
    expect(screen.queryByText('AR Aging')).not.toBeInTheDocument();
    expect(screen.getByText('No saved catalog is available offline yet.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('AR Aging')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('serves the last successful catalog offline, with a banner and a retry', async () => {
    stubCatalog();
    const first = render(<MarketplaceApp />);
    expect(await screen.findByText('AR Aging')).toBeInTheDocument();
    first.unmount();

    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(jsonResponse(catalog()));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    const banner = await screen.findByRole('status');
    expect(within(banner).getByText('Offline')).toBeInTheDocument();
    expect(within(banner).getByText(/Showing the last saved catalog/)).toBeInTheDocument();
    expect(within(banner).getByText(/Nothing was invented/)).toBeInTheDocument();
    expect(screen.getByText('AR Aging')).toBeInTheDocument();

    await user.click(within(banner).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
    expect(screen.getByText('AR Aging')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not fall back to the cache for a filtered catalog request', async () => {
    stubCatalog();
    const first = render(<MarketplaceApp />);
    expect(await screen.findByText('AR Aging')).toBeInTheDocument();
    first.unmount();

    window.history.replaceState({}, '', '/marketplace/search?q=overdue');
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);
    render(<MarketplaceApp />);
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('No saved catalog for these filters is available offline.')).toBeInTheDocument();
    expect(screen.queryByText('AR Aging')).not.toBeInTheDocument();
  });
});
