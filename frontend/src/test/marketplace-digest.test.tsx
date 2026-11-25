// The digest copy control: a visible success for two seconds, and one honest
// manual way out when the clipboard is missing or refuses.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { detail, detailResponse } from './marketplace-fixtures';

const here = dirname(fileURLToPath(import.meta.url));
const marketplaceCss = readFileSync(resolve(here, '..', 'marketplace', 'marketplace.css'), 'utf8');

const DIGEST = detail().digest;
const COPY_FAILED = 'Could not copy automatically. The full digest is selected below; '
  + 'press Ctrl+C (or Cmd+C on a Mac).';

const clipboard = { writeText: vi.fn() };

/** Put the navigator where the copy control reads it, or remove it. */
function setClipboard(value: unknown): void {
  Object.defineProperty(window.navigator, 'clipboard', { configurable: true, value });
}

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

/** Let pending promises and effects settle under fake timers. */
async function settle(): Promise<void> {
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
}

describe('the digest copy control', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/marketplace/plugin/ar-aging');
    clipboard.writeText.mockReset();
    setClipboard(clipboard);
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/marketplace/plugin/')) return jsonResponse(detailResponse());
      return jsonResponse({});
    }));
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    setClipboard(undefined);
    window.history.replaceState({}, '', '/');
  });

  it('shows a check and the copied status for two seconds, then returns to copy', async () => {
    vi.useFakeTimers();
    clipboard.writeText.mockResolvedValue(undefined);
    render(<MarketplaceApp />);
    await settle();

    const button = screen.getByRole('button', { name: 'Copy digest' });
    expect(button.querySelector('svg')?.getAttribute('width')).toBe('14');
    expect(button.querySelector('svg')?.getAttribute('height')).toBe('14');
    fireEvent.click(button);
    await settle();

    expect(clipboard.writeText).toHaveBeenCalledWith(DIGEST);
    expect(button).toHaveAttribute('aria-label', 'Digest copied');
    expect(button.querySelector('rect')).toBeNull();
    expect(button.querySelector('path')?.getAttribute('d')).toBe('m4 12 5 5L20 6');
    expect(button.querySelector('svg')?.getAttribute('width')).toBe('14');
    expect(screen.getByText('Digest copied')).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(button).toHaveAttribute('aria-label', 'Copy digest');
    expect(button.querySelector('rect')).not.toBeNull();
    expect(screen.queryByText('Digest copied')).toBeNull();
  });

  it('offers the full digest in a focused selected field when the clipboard refuses', async () => {
    vi.useFakeTimers();
    clipboard.writeText.mockRejectedValue(new Error('denied'));
    render(<MarketplaceApp />);
    await settle();

    fireEvent.click(screen.getByRole('button', { name: 'Copy digest' }));
    await settle();

    expect(screen.getByText(COPY_FAILED)).toBeInTheDocument();
    const field = screen.getByLabelText('Full digest') as HTMLInputElement;
    expect(field.readOnly).toBe(true);
    expect(field.value).toBe(DIGEST);
    expect(document.activeElement).toBe(field);
    expect(field.selectionStart).toBe(0);
    expect(field.selectionEnd).toBe(DIGEST.length);

    // A later success takes both away and shows the check.
    clipboard.writeText.mockResolvedValue(undefined);
    fireEvent.click(screen.getByRole('button', { name: 'Copy digest' }));
    await settle();
    expect(screen.queryByText(COPY_FAILED)).toBeNull();
    expect(screen.queryByLabelText('Full digest')).toBeNull();
    expect(screen.getByRole('button', { name: 'Digest copied' })).toBeInTheDocument();
  });

  it('takes the manual path when the clipboard API is missing', async () => {
    vi.useFakeTimers();
    setClipboard(undefined);
    render(<MarketplaceApp />);
    await settle();

    fireEvent.click(screen.getByRole('button', { name: 'Copy digest' }));
    await settle();

    expect(screen.getByText(COPY_FAILED)).toBeInTheDocument();
    const field = screen.getByLabelText('Full digest') as HTMLInputElement;
    expect(field.value).toBe(DIGEST);
    expect(document.activeElement).toBe(field);
    expect(field.selectionEnd).toBe(DIGEST.length);
  });

  it('pins the fallback wrap and the icon button box in the marketplace sheet', () => {
    expect(marketplaceCss).toMatch(/\.mkt-digest \{[^}]*flex-wrap: wrap;/);
    expect(marketplaceCss).toMatch(/\.mkt-digest-fallback \{[^}]*white-space: normal;/);
    expect(marketplaceCss).toMatch(/\.mkt-digest-fallback \{[^}]*overflow-wrap: anywhere;/);
    expect(marketplaceCss).toMatch(/\.mkt-digest-fallback \{[^}]*min-width: 0;/);
    expect(marketplaceCss).toMatch(/\.mkt-icon-btn \{[^}]*width: 28px;[^}]*height: 28px;/);
  });
});
