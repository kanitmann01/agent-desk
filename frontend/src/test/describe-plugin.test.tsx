// Spec 024, ticket 08: describing a plugin in plain English. With an AI
// connection the description fills the tile's choices in, inside a dialog
// that shows the fill happening and says so afterwards. Without one the
// walk is exactly the plain form post it was.
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

/** Stub the server: the probe answers, the describe post answers the fill. */
function stubServer(available: boolean, fill: unknown = FILLED) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/wizard/availability')) {
      return jsonResponse({ autofill: available });
    }
    if (url.includes('/wizard/start')) {
      return jsonResponse(fill, 201);
    }
    return jsonResponse(catalog());
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

async function openDescribe() {
  render(<MarketplaceApp />);
  await screen.findByRole('heading', { level: 1, name: 'Find plugins' });
  const button = screen.getByRole('button', { name: 'Describe a plugin in plain English' });
  return button.closest('form') as HTMLFormElement;
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
    const form = await openDescribe();

    await userEvent.click(within(form).getByRole('button'));
    // No dialog: the plain post is the walk a desk without a connection needs.
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(screen.queryByText(/Add an AI connection/)).toBeNull();
  });

  it('opens the description dialog when a connection is saved', async () => {
    stubServer(true);
    const form = await openDescribe();

    await userEvent.click(within(form).getByRole('button'));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByLabelText('Describe the plugin you want')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Fill it in for me' })).toBeInTheDocument();
  });

  it('disables the fill for an empty description and starts no request when pressed', async () => {
    const fetchMock = stubServer(true);
    const form = await openDescribe();

    await userEvent.click(within(form).getByRole('button'));
    const dialog = await screen.findByRole('dialog');
    const fill = within(dialog).getByRole('button', { name: 'Fill it in for me' });
    expect(fill).toBeDisabled();

    await userEvent.click(fill);
    const fillRequests = fetchMock.mock.calls
      .filter(([input]) => String(input).includes('/wizard/start'));
    expect(fillRequests).toHaveLength(0);
  });

  it('enables the fill after text is typed and starts one request when pressed', async () => {
    const fetchMock = stubServer(true);
    const form = await openDescribe();

    await userEvent.click(within(form).getByRole('button'));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Describe the plugin you want'),
                         'A morning list of my mail');
    const fill = within(dialog).getByRole('button', { name: 'Fill it in for me' });
    expect(fill).toBeEnabled();

    await userEvent.click(fill);
    const fillRequests = fetchMock.mock.calls
      .filter(([input]) => String(input).includes('/wizard/start'));
    expect(fillRequests).toHaveLength(1);
    expect(await within(dialog).findByText('My mail')).toBeInTheDocument();
  });

  it('shows the fill happening, then says the choices were filled in', async () => {
    let release: (value: Response) => void = () => {};
    const held = new Promise<Response>((resolve) => { release = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/wizard/availability')) return jsonResponse({ autofill: true });
      if (url.includes('/wizard/start')) return held;
      return jsonResponse(catalog());
    }));

    const form = await openDescribe();
    await userEvent.click(within(form).getByRole('button'));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Describe the plugin you want'),
                         'A morning list of my mail');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Fill it in for me' }));

    // The dialog is busy: one prompt per field, no labels yet.
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
    // Nothing is installed by the fill: the walk is the next step.
    expect(within(dialog).getByRole('button', { name: 'Change or continue' })).toBeInTheDocument();
  });

  it('says the fill did not run when the call fails, and offers the walk', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/wizard/availability')) return jsonResponse({ autofill: true });
      if (url.includes('/wizard/start')) return jsonResponse({ error: 'boom' }, 500);
      return jsonResponse(catalog());
    }));

    const form = await openDescribe();
    await userEvent.click(within(form).getByRole('button'));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Describe the plugin you want'),
                         'A morning list of my mail');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Fill it in for me' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The fill did not run');
    // A connection exists, so the copy never tells them to add one.
    expect(within(dialog).queryByText(/Add an AI connection/)).toBeNull();
    expect(within(dialog).getByRole('link', { name: 'Continue without the fill' }))
      .toHaveAttribute('href', '/wizard/start');
  });
});
