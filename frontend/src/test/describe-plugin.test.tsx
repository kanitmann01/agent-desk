// Spec 024, ticket 08: describing a plugin in plain English. With an AI
// connection the description fills the tile's choices in, inside a dialog
// that shows the fill happening and says so afterwards. Without one the
// walk is exactly the plain form post it was, and the page invites the
// connection instead of showing an error.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';
import { catalog } from './marketplace-fixtures';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

const FILLED = {
  id: 'wiz-abc',
  state: 'questions',
  description: 'A morning list of my mail',
  answers: {
    source: 'My mail',
    show: 'The items that need me',
    look: 'A list',
    update: 'Each morning at 8',
  },
  reasons: {
    source: 'It reads your mail folder.',
    show: 'It lists what is waiting on you.',
  },
  questions: [],
  draft: null,
};

/**
 * Stub the server: the availability probe answers, and the describe post
 * answers with the fill. Anything else gets the empty catalog.
 */
function stubServer(available: boolean, fill: unknown = FILLED) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/wizard/availability')) {
      return jsonResponse({ autofill: available });
    }
    if (url.includes('/wizard/start')) {
      return jsonResponse(fill, 201);
    }
    return jsonResponse(catalog());
  }));
}

describe('describing a plugin (spec 024)', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState({}, '', '/marketplace');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('stays a plain form post when no AI connection is saved', async () => {
    stubServer(false);
    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'Find plugins' });

    const button = screen.getByRole('button', { name: 'Describe a plugin in plain English' });
    const form = button.closest('form');
    expect(form).toHaveAttribute('method', 'post');
    expect(form).toHaveAttribute('action', '/wizard/start');
    // The description field is the dialog's; without a connection there is
    // no dialog to open, so the page never grows a second input.
    await waitFor(() => {
      expect(screen.queryByLabelText('Describe the plugin you want')).toBeNull();
    });
    expect(screen.queryByText(/Add an AI connection/)).toBeNull();
  });

  it('offers the description field once a connection is saved', async () => {
    stubServer(true);
    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'Find plugins' });

    expect(await screen.findByLabelText('Describe the plugin you want')).toBeInTheDocument();
    // The plain action still works as a form for anyone without script.
    const form = screen.getByRole('button', { name: 'Describe a plugin in plain English' })
      .closest('form');
    expect(form).toHaveAttribute('action', '/wizard/start');
  });

  it('shows the fill happening, then says the choices were filled in', async () => {
    stubServer(true);
    let release: (value: Response) => void = () => {};
    const held = new Promise<Response>((resolve) => { release = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/wizard/availability')) return jsonResponse({ autofill: true });
      if (url.includes('/wizard/start')) return held;
      return jsonResponse(catalog());
    }));

    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'Find plugins' });
    const field = await screen.findByLabelText('Describe the plugin you want');
    await userEvent.type(field, 'A morning list of my mail');
    await userEvent.click(screen.getByRole('button', { name: 'Describe a plugin in plain English' }));

    // The dialog is open and busy: one prompt per field, no labels yet.
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveAttribute('aria-busy', 'true');
    expect(within(dialog).getByText('What it watches')).toBeInTheDocument();
    expect(within(dialog).queryByText('My mail')).toBeNull();

    release(jsonResponse(FILLED, 201));

    // Each row becomes the chosen label and the dialog says it filled them.
    expect(await within(dialog).findByText('My mail')).toBeInTheDocument();
    expect(within(dialog).getByText('The items that need me')).toBeInTheDocument();
    expect(within(dialog).getByText('Each morning at 8')).toBeInTheDocument();
    expect(within(dialog).getByText('It reads your mail folder.')).toBeInTheDocument();
    expect(within(dialog).getByRole('status'))
      .toHaveTextContent('Filled in from your description');
    // Nothing was installed by the fill: the walk is the next step.
    expect(within(dialog).getByRole('button', { name: 'Change or continue' })).toBeInTheDocument();
  });

  it('says the fill did not run when the call fails, and still offers the walk', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/wizard/availability')) return jsonResponse({ autofill: true });
      if (url.includes('/wizard/start')) return jsonResponse({ error: 'boom' }, 500);
      return jsonResponse(catalog());
    }));

    render(<MarketplaceApp />);
    await screen.findByRole('heading', { level: 1, name: 'Find plugins' });
    const field = await screen.findByLabelText('Describe the plugin you want');
    await userEvent.type(field, 'A morning list of my mail');
    await userEvent.click(screen.getByRole('button', { name: 'Describe a plugin in plain English' }));

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('alert'))
      .toHaveTextContent('The fill did not run');
    // A connection exists, so the copy never tells them to add one.
    expect(within(dialog).queryByText(/Add an AI connection/)).toBeNull();
    expect(within(dialog).getByRole('link', { name: 'Continue without the fill' }))
      .toHaveAttribute('href', '/wizard/start');
  });
});
