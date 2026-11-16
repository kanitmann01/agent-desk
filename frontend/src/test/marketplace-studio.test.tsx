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
});
