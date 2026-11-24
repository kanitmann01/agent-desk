// Turn the server's raw scope leaves into sentences, and derive the
// "can never" promises from the declared capabilities. Nothing here
// widens or guesses a permission: an absent list is a true absence.
import type { MarketCapabilities } from './types';

export interface ScopeSentence {
  scope: string;
  sentence: string;
  setting: string;
  positive: boolean;
}

/**
 * Turn one scope leaf's value into the phrase a person reads.
 *
 * A workspace-relative path is named as "your workspace", surrounding list
 * brackets are dropped, and an empty value reads as "nothing".
 */
function valueText(value: string): string {
  const raw = value.replace(/^${workspace}/, 'your workspace');
  return raw.replace(/^\[|\]$/g, '') || 'nothing';
}

/** True for scope leaves that describe a refusal rather than a power. */
function isNegative(prefix: string, value: string): boolean {
  const v = value.trim().toLowerCase();
  if (prefix.startsWith('shell')) return true;
  return v === 'false' || v === 'none' || v === '[]' || v === 'null';
}

/**
 * Turn one `prefix:value` scope leaf into the sentence shown beside a plugin.
 *
 * The prefix selects the setting it belongs under; an unknown prefix falls
 * back to a generic settings sentence. Severity is not lost either: a scope
 * that refuses something comes back with `positive` false, which is what
 * `visibleScopes` filters on.
 */
export function describeScope(scope: string): ScopeSentence {
  const at = scope.indexOf(':');
  const prefix = (at >= 0 ? scope.slice(0, at) : scope).trim();
  const value = at >= 0 ? scope.slice(at + 1).trim() : '';
  const positive = !isNegative(prefix, value);
  if (prefix === 'filesystem.read') {
    return { scope, positive, setting: 'Files and folders',
      sentence: value ? `Reads files matching ${valueText(value)}.` : 'Reads no files.' };
  }
  if (prefix === 'filesystem.write') {
    return { scope, positive, setting: 'Files and folders',
      sentence: value ? `Writes files matching ${valueText(value)}.` : 'Writes no files.' };
  }
  if (prefix === 'network.allow') {
    return { scope, positive, setting: 'Network access',
      sentence: value ? `Contacts ${valueText(value)}.` : 'Contacts no network hosts.' };
  }
  if (prefix === 'llm.allow') {
    return { scope, positive, setting: 'Assistant model',
      sentence: positive ? 'Sends its widget data to the assistant model.' : 'Does not call the assistant model.' };
  }
  return { scope, positive, setting: 'Plugin settings',
    sentence: positive ? `Uses ${prefix} set to ${valueText(value)}.` : `Does not use ${prefix}.` };
}

/** Scopes worth showing a person: refusals are dropped. */
export function visibleScopes(scopes: string[]): string[] {
  return scopes.filter((scope) => describeScope(scope).positive);
}

/**
 * True when a plugin's declared capabilities ask to reach the web.
 *
 * The catalog DTO lists requested hosts under `network` (from permissions
 * and optionalPermissions) and data-source kinds under `sources`; an HTTP
 * source reads as `http-get`. Either one means the plugin needs the plugin
 * runner's HTTP transport.
 */
export function asksForWeb(
  capabilities: Pick<MarketCapabilities, 'network' | 'sources'> | undefined,
): boolean {
  if (!capabilities) return false;
  const hosts = capabilities.network ?? [];
  const sources = capabilities.sources ?? [];
  return hosts.length > 0 || sources.some((source) => source.toLowerCase().startsWith('http'));
}

/**
 * State the promises a plugin's declared capabilities imply.
 *
 * An empty filesystem or network list is a true absence, so the wording
 * changes from "outside the paths above" to "no file at all" instead of
 * implying a limit that was never declared.
 */
export function canNever(capabilities: MarketCapabilities): string[] {
  const lines: string[] = [];
  lines.push(capabilities.filesystem.length === 0
    ? 'It can never read or write a file on this computer.'
    : 'It can never read or write files outside the paths listed above.');
  lines.push(capabilities.network.length === 0
    ? 'It can never open a network connection.'
    : 'It can never contact a host outside the hosts listed above.');
  lines.push('It can never run shell commands or start another program.');
  lines.push('It can never change its own permission scopes or other plugins.');
  return lines;
}

/** The same promises, derived from a flat scope list (packs, staged updates). */
export function canNeverFromScopes(scopes: string[]): string[] {
  const hasFs = scopes.some((scope) => scope.startsWith('filesystem.'));
  const hasNet = scopes.some((scope) => scope.startsWith('network.'));
  return [
    hasFs ? 'It can never read or write files outside the paths listed above.'
      : 'It can never read or write a file on this computer.',
    hasNet ? 'It can never contact a host outside the hosts listed above.'
      : 'It can never open a network connection.',
    'It can never run shell commands or start another program.',
    'It can never change its own permission scopes or other plugins.',
  ];
}

/**
 * Show the leading characters of a digest for display beside a plugin.
 *
 * The `sha256:` prefix is dropped before truncating, and an empty digest
 * reads as "no digest" rather than as a match.
 */
export function shortDigest(digest: string, length = 12): string {
  if (!digest) return 'no digest';
  const clean = digest.startsWith('sha256:') ? digest.slice(7) : digest;
  return clean.slice(0, length);
}

/** Pilot budget, or an honest blank when the server recorded none. */
export function pilotBudget(pilot: { views: number; remaining: number } | null | undefined): string {
  if (!pilot || (pilot.views === 0 && pilot.remaining === 0)) return 'Not recorded';
  return `${pilot.remaining} of ${pilot.views} views left`;
}

/**
 * Format a byte count for a person, in B, KB or MB.
 *
 * Counts that are not finite or not positive read as "0 B"; everything above
 * a kilobyte keeps one decimal.
 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Format an ISO timestamp as a short local date.
 *
 * An empty value reads as "not recorded", and a value `Date` cannot parse is
 * returned unchanged rather than shown as "Invalid Date".
 */
export function formatDate(value: string): string {
  if (!value) return 'not recorded';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}
