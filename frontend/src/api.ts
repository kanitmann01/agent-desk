// Same-origin API access. Every call rides the session cookie and the
// one guard the server already runs; nothing here talks to anywhere
// else. A 401 means the session expired and only the shortcut fixes it.
import type { InsightAnswer, InsightPress, InsightRefusal } from './types';

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

// The reading's press: one model call, sent only when the person presses
// the button. The route and the body come from the press the card already
// carried, so the SPA never invents what travels, and `stage` is the one
// field pressing a second button adds.
export type PressBody = Omit<InsightPress, 'label' | 'route'> & { stage?: boolean };

export interface PressResult {
  ok: boolean;
  status: number;
  /** The answer or the refusal: `ok` is what tells them apart. */
  data: Partial<InsightAnswer & InsightRefusal>;
}

export async function pressReading(route: string, body: PressBody): Promise<PressResult> {
  const result = await postJson(route, body);
  const data = (typeof result.data === 'object' && result.data !== null ? result.data : {}) as Partial<
    InsightAnswer & InsightRefusal
  >;
  return { ok: result.ok, status: result.status, data };
}

export const SESSION_EXPIRED_TITLE = 'Session required';
export const SESSION_EXPIRED_MESSAGE = 'Open Nexuus Bot from its shortcut to get a fresh link.';
export const UNREACHABLE = 'The dashboard could not reach its own server';
