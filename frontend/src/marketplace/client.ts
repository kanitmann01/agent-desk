// Same-origin marketplace calls. Every failure becomes a MarketApiError
// carrying the server's stable code and details, so a surface never has
// to invent an error message or a status.
import { getJson, postJson, SESSION_EXPIRED_MESSAGE } from '../api';

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

export function marketErrorText(err: unknown): string {
  if (err instanceof MarketApiError) return err.message;
  return 'The marketplace could not reach its own server. Try again.';
}
