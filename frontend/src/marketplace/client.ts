// Same-origin marketplace calls. Every failure becomes a MarketApiError
// carrying the server's stable code and details, so a surface never has
// to invent an error message or a status.
import { getJson, postFile, postJson, SESSION_EXPIRED_MESSAGE } from '../api';
import type { InstancesResponse } from './types';

export class MarketApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;

  constructor(status: number, code: string, message: string,
              details: Record<string, unknown> = {}) {
    super(message);
    this.name = 'MarketApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function unwrap(status: number, data: unknown): never {
  const payload = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>;
  const code = typeof payload.error === 'string' ? payload.error : 'marketplace:error';
  const message = status === 401
    ? SESSION_EXPIRED_MESSAGE
    : typeof payload.message === 'string'
      ? payload.message
      : 'The marketplace could not complete that request.';
  const details = (payload.details && typeof payload.details === 'object'
    ? payload.details as Record<string, unknown>
    : {});
  throw new MarketApiError(status, code, message, details);
}

export async function getMarket<T>(path: string): Promise<T> {
  const res = await getJson(path);
  if (!res.ok) unwrap(res.status, res.data);
  return res.data as T;
}

export async function postMarket<T>(path: string, body?: unknown): Promise<T> {
  const res = await postJson(path, body);
  if (!res.ok) unwrap(res.status, res.data);
  return res.data as T;
}

// Instance setup (T5): the manage view reads a plugin's instances and
// drives the same per-instance endpoints the dashboard card uses. The
// errors ride the same {error, message} envelope as the marketplace
// calls, so a refusal surfaces with its server message.
export async function getInstances(pluginId: string): Promise<InstancesResponse> {
  const res = await getJson(`/api/plugins/${encodeURIComponent(pluginId)}/instances`);
  if (!res.ok) unwrap(res.status, res.data);
  return res.data as InstancesResponse;
}

export async function postInstance<T>(pluginId: string, tail: string, body?: unknown): Promise<T> {
  const res = await postJson(`/api/plugins/${encodeURIComponent(pluginId)}/instances${tail}`, body);
  if (!res.ok) unwrap(res.status, res.data);
  return res.data as T;
}

/**
 * Post one file to an instance route as raw bytes, unwrapping a failure
 * the same way the JSON calls do, so a refused upload arrives as a
 * sentence instead of a status code.
 */
export async function postUpload<T>(pluginId: string, tail: string, file: File): Promise<T> {
  const res = await postFile(`/api/plugins/${encodeURIComponent(pluginId)}/instances${tail}`, file);
  if (!res.ok) unwrap(res.status, res.data);
  return res.data as T;
}

export function marketErrorText(err: unknown): string {
  if (err instanceof MarketApiError) return err.message;
  return 'The marketplace could not reach its own server. Try again.';
}
