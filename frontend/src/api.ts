// Same-origin API access. Every call rides the session cookie and the
// one guard the server already runs; nothing here talks to anywhere
// else. A 401 means the session expired and only the shortcut fixes it.

export interface ApiResult<T = unknown> {
  ok: boolean;
  status: number;
  data: T;
}

export async function getJson(url: string): Promise<ApiResult> {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  const data = await safeJson(response);
  return { ok: response.ok, status: response.status, data };
}

export async function postJson(url: string, body?: unknown): Promise<ApiResult> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  const data = await safeJson(response);
  return { ok: response.ok, status: response.status, data };
}

async function safeJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

export const SESSION_EXPIRED_TITLE = 'Session required';
export const SESSION_EXPIRED_MESSAGE = 'Open Agent Desk from its shortcut to get a fresh link.';
export const UNREACHABLE = 'The dashboard could not reach its own server';
