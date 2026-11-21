// Same-origin API access. Every call rides the session cookie and the
// one guard the server already runs; nothing here talks to anywhere
// else. A 401 means the session expired and only the shortcut fixes it.
import type { InsightAnswer, InsightPress, InsightRefusal } from './types';

export interface ApiResult<T = unknown> {
  ok: boolean;
  status: number;
  data: T;
}

/**
 * Fetch a JSON document over the session cookie and return the status with its
 * parsed body, so callers branch on `ok` instead of catching.
 */
export async function getJson(url: string): Promise<ApiResult> {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  const data = await safeJson(response);
  return { ok: response.ok, status: response.status, data };
}

/**
 * Post a JSON body and return the status with the parsed answer.
 *
 * The body defaults to an empty object, which is what the routes taking no
 * arguments expect.
 */
export async function postJson(url: string, body?: unknown): Promise<ApiResult> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  const data = await safeJson(response);
  return { ok: response.ok, status: response.status, data };
}

/**
 * Post a file as raw bytes: the file is the whole body, not multipart,
 * and the answer is still JSON.
 */
export async function postFile(url: string, file: File): Promise<ApiResult> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream', Accept: 'application/json' },
    body: file,
  });
  return { ok: response.ok, status: response.status, data: await safeJson(response) };
}

/**
 * Parse a response body as JSON, yielding an empty object for anything else.
 *
 * Never throws, so callers read the status rather than catching.
 */
async function safeJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

// The reading's press: one model call, sent only when the person presses
// the button. The body is the press the card carried, verbatim minus its
// label and route, and `stage` is the one field pressing a second button
// adds; the wire shape is the server's, so the SPA never re-assembly-lines
// it field by field.
export type PressBody = Omit<InsightPress, 'label' | 'route'> & { stage?: boolean };

export interface PressResult {
  ok: boolean;
  status: number;
  /** The answer or the refusal: `ok` is what tells them apart. */
  data: Partial<InsightAnswer & InsightRefusal>;
}

/**
 * Send one press and narrow its result to the reading's own shapes, so
 * callers branch on `ok` alone and never cast the data themselves.
 */
export async function pressReading(route: string, body: PressBody): Promise<PressResult> {
  const result = await postJson(route, body);
  const data = (typeof result.data === 'object' && result.data !== null ? result.data : {}) as Partial<
    InsightAnswer & InsightRefusal
  >;
  return { ok: result.ok, status: result.status, data };
}

export const SESSION_EXPIRED_TITLE = 'Session required';
export const SESSION_EXPIRED_MESSAGE = 'Open Nexuus Bot from its shortcut to get a fresh link.';
