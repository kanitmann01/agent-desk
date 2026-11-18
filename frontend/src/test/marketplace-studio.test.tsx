// Studio must show the real validator's findings and keep publish locked
// until the validator passes. There is no fake success path in the test.
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { installedResponse } from './marketplace-fixtures';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

describe('Plugin Studio', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/marketplace/studio');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, '', '/');
  });

  it('shows validator failures, keeps publish disabled and sends the inline manifest', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/marketplace/validate') {
        expect(init?.method).toBe('POST');
        const body = JSON.parse(String(init?.body)) as {
          manifest: { id: string; schemaVersion: number };
          widgetUi: { type: string; elements: unknown[] };
          sample: { bindings: Record<string, unknown>; state: string };
        };
        expect(body.manifest.id).toBe('late-invoices');
        expect(body.manifest.schemaVersion).toBe(2);
        expect(body.widgetUi.type).toBe('card');
        expect(body.sample.state).toBe('ok');
        expect(body.sample.bindings).toHaveProperty('value');
        return jsonResponse({
          ok: false,
          failures: [{
            code: 'manifest:summary-too-long',
            message: 'summary must be at most 120 characters',
          }],
        });
      }
      return jsonResponse(installedResponse([]));
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Plugin Studio' })).toBeInTheDocument();
    const publish = screen.getByRole('button', { name: 'Publish for review' });
    expect(publish).toBeDisabled();

    await user.type(screen.getByLabelText('Plugin id'), 'late-invoices');
    await user.type(screen.getByLabelText('Name'), 'Late invoices');
    expect(screen.getByLabelText('Live manifest preview')).toHaveTextContent('"id": "late-invoices"');

    await user.click(screen.getByRole('button', { name: 'Run validator' }));

    expect(await screen.findByText('Validator found problems.')).toBeInTheDocument();
    expect(screen.getByText('manifest:summary-too-long')).toBeInTheDocument();
    expect(screen.getByText('summary must be at most 120 characters')).toBeInTheDocument();
    expect(publish).toBeDisabled();
    expect(screen.queryByRole('heading', { name: 'Pending review' })).not.toBeInTheDocument();
  });

  // Creation is not finished at "pending review": the personal path must
  // install the validated tree on this desk and say so.
  it('installs the validated draft on this desk without an admin switch', async () => {
    let installBody: { manifest: { id: string }; widgetUi: unknown; sample: unknown } | null = null;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/marketplace/validate') {
        return jsonResponse({ ok: true, failures: [] });
      }
      if (url === '/api/marketplace/studio/install') {
        installBody = JSON.parse(String(init?.body)) as typeof installBody;
        return jsonResponse({ id: 'team-notes', version: '0.1.0', status: 'installed' });
      }
      return jsonResponse(installedResponse([]));
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await user.type(await screen.findByLabelText('Plugin id'), 'team-notes');
    await user.type(screen.getByLabelText('Name'), 'Team notes');
    const install = screen.getByRole('button', { name: 'Install on this desk' });
    expect(install).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Run validator' }));
    expect(await screen.findByText('Validator passed.')).toBeInTheDocument();
    await user.click(install);

    expect(await screen.findByRole('heading', { name: 'Installed on this desk' })).toBeInTheDocument();
    const sent = installBody as { manifest: { id: string }; widgetUi: unknown; sample: unknown } | null;
    expect(sent?.manifest.id).toBe('team-notes');
    expect(sent?.widgetUi).toBeTruthy();
    expect(sent?.sample).toBeTruthy();
  });

  // Regression: the generated widget.ui.json named each element's kind in
  // `kind`, the validator reads `type`, so every Studio draft failed with
  // "unknown element kind: None" and Publish never unlocked.
  it('sends widget elements typed the way the validator reads them, then publishes', async () => {
    let sentElements: Record<string, unknown>[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/marketplace/validate') {
        const body = JSON.parse(String(init?.body)) as { widgetUi: { elements: Record<string, unknown>[] } };
        sentElements = body.widgetUi.elements;
        return jsonResponse({ ok: true, failures: [] });
      }
      if (url === '/api/marketplace/publish') {
        return jsonResponse({ pendingId: 'p-1', status: 'pending-review', validation: { ok: true, failures: [] } }, 202);
      }
      return jsonResponse(installedResponse([]));
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MarketplaceApp />);

    await user.type(await screen.findByLabelText('Plugin id'), 'team-notes');
    await user.type(screen.getByLabelText('Name'), 'Team notes');
    await user.click(screen.getByRole('button', { name: 'Run validator' }));
    expect(await screen.findByText('Validator passed.')).toBeInTheDocument();
    expect(sentElements.length).toBeGreaterThan(0);
    for (const element of sentElements) {
      expect(typeof element.type).toBe('string');
      expect(element).not.toHaveProperty('kind');
    }

    await user.type(screen.getByLabelText(/Changelog/), 'First version.');
    await user.click(screen.getByLabelText(/I grant this desk/));
    await user.click(screen.getByRole('button', { name: 'Publish for review' }));
    expect(await screen.findByRole('heading', { name: 'Pending review' })).toBeInTheDocument();
  });
});
