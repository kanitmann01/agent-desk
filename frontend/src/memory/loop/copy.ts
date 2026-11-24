// The Memory page's words, kept in one place so the page and its tests
// agree. Plain labels; counts carry their own nouns.
import type { RemovalDone, RemovalPlan } from './types';

/** The number with its noun, pluralised unless the count is exactly one. */
export function count(n: number, noun: string, plural = `${noun}s`): string {
  return `${n} ${n === 1 ? noun : plural}`;
}

const dateFormat = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
const timeFormat = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' });

// "12:04" today, "Nov 3" otherwise. The page shows when, never "ago".
/**
 * The time of a row: clock time for today, "Nov 3" otherwise, or "" when absent.
 *
 * Both arguments are epoch seconds; today is read from the local calendar date.
 */
export function stamp(ts: number | null | undefined, now = Date.now() / 1000): string {
  if (ts === null || ts === undefined) return '';
  const date = new Date(ts * 1000);
  const today = new Date(now * 1000);
  return date.toDateString() === today.toDateString() ? timeFormat.format(date) : dateFormat.format(date);
}

/** The capture channels as a readable list, or "no channel" when none are on. */
export function channelList(labels: string[]): string {
  if (labels.length === 0) return 'no channel';
  if (labels.length === 1) return labels[0];
  return `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`;
}

/** The user-facing name of an extraction method; unknown ones pass through. */
export function methodLabel(method: string): string {
  return method === 'model' ? 'AI' : method === 'rules' ? 'Rules' : method;
}

export const TARGET_NOUN: Record<RemovalPlan['target']['type'], string> = {
  fact: 'fact',
  source: 'excerpt',
  entity: 'entity',
  observation: 'observation',
};

// The confirm button says exactly what goes.
/** The confirm button's text, naming exactly what the removal takes. */
export function removeLabel(plan: RemovalPlan): string {
  if (plan.target.type === 'observation') return 'Remove observation';
  if (plan.facts.length === 0) return `Remove ${TARGET_NOUN[plan.target.type]}`;
  return `Remove ${count(plan.facts.length, 'fact')}`;
}

// One line for the undo bar: what went, then what else changed.
/** The undo bar's single line: what was removed, then what else changed. */
export function removedSummary(done: RemovalDone): string {
  const parts: string[] = [];
  if (done.facts.length) parts.push(`Removed ${count(done.facts.length, 'fact')}`);
  else if (done.observationsRemoved.length) parts.push(`Removed ${count(done.observationsRemoved.length, 'observation')}`);
  else parts.push('Removed');
  if (done.observationsUpdated.length) parts.push(`${count(done.observationsUpdated.length, 'observation')} rewritten`);
  if (done.facts.length && done.observationsRemoved.length) parts.push(`${count(done.observationsRemoved.length, 'observation')} removed`);
  if (done.observationsFlagged.length) parts.push(`${count(done.observationsFlagged.length, 'observation')} flagged`);
  if (done.entitiesRemoved.length) parts.push(`${count(done.entitiesRemoved.length, 'entity', 'entities')} forgotten`);
  if (done.factsRestored.length) parts.push(`${count(done.factsRestored.length, 'older fact')} back in recall`);
  return parts.join(' · ');
}

// Under each "Read from" switch: what that channel hands to capture.
export const CHANNEL_HINT: Record<string, string> = {
  assistant: 'Your questions and its answers',
  research: 'Your questions and the sourced summary',
  workbook: 'Rows that change in the watched workbook',
};

// Who wrote an observation, in the row's meta line.
/** Who produced an observation, for the row's meta line. */
export function observationWriter(obs: { derived: string; method: string | null }): string {
  if (obs.derived !== 'consolidated') return 'Reflected by your AI';
  return obs.method === 'model' ? 'Summarized by your AI' : 'Built-in summary';
}

// The stored-knowledge lists show this many rows until "Show all".
export const LIST_CAP = 8;
