// What the desk shows for a cell kind while the Sample data switch is
// on and no real source fills that cell. The content is one small
// world that matches the seeded sample folder: the same accounts as
// the sample workbook, the same meetings as the sample calendar, the
// same subjects as the header-only sample mail. Every cell that shows
// it carries the SAMPLE DATA tag; nothing here is ever shown when the
// switch is off.
import type { TrackerView } from '../types';

export interface DigestItem {
  at: Date;
  source: 'MAIL' | 'CAL' | 'DESK';
  title: string;
  detail: string;
}

export interface WatchLine {
  kind: 'same' | 'removed' | 'added';
  text: string;
}

export interface WatchView {
  name: string;
  url: string;
  checkedAt: Date;
  changes: number;
  lines: WatchLine[];
  /** Changes per day over the last week, oldest first. */
  history: number[];
}

/** A copy of now moved by the given number of hours, floored to the minute. */
function hoursFrom(now: Date, hours: number): Date {
  const at = new Date(now.getTime() + hours * 3600_000);
  at.setSeconds(0, 0);
  return at;
}

/** The digest: the sample calendar's two meetings and the three mails. */
export function sampleDigest(now: Date): DigestItem[] {
  return [
    { at: hoursFrom(now, 2), source: 'CAL', title: 'Q4 pipeline review', detail: 'Room Beaufort, 6 people' },
    { at: hoursFrom(now, -3), source: 'MAIL', title: 'Q4 plan', detail: 'From sales-ops@example.com' },
    { at: hoursFrom(now, -6), source: 'MAIL', title: 'Field services rollout', detail: 'From operations@example.com' },
    { at: hoursFrom(now, -9), source: 'MAIL', title: 'Care plan pricing', detail: 'From finance@example.com, Cc' },
    { at: hoursFrom(now, 4), source: 'CAL', title: 'Care plan check-in', detail: 'Call, 3 people' },
  ].sort((a, b) => a.at.getTime() - b.at.getTime()) as DigestItem[];
}

/** A workbook tracker on the sample workbook's Closed Won column. */
export const SAMPLE_TRACKER: TrackerView = {
  name: 'Closed Won, this quarter',
  value: '412,300',
  unit: 'USD',
  delta: '+18,850',
  direction: 'up',
  points: [318_400, 326_900, 331_200, 329_800, 344_100, 352_600, 360_050, 371_900, 368_300, 384_700, 393_450, 412_300],
  file: 'sample-sales.xlsx',
  paceNote: '6 weeks left in the quarter',
  goal: { value: '500,000', unit: 'USD' },
};

/** Page watch on a supplier's public pricing page. */
export function sampleWatch(now: Date): WatchView {
  return {
    name: 'Halvorsen Freight rates',
    url: 'halvorsen-freight.example/rates',
    checkedAt: hoursFrom(now, -1),
    changes: 2,
    lines: [
      { kind: 'same', text: 'Pallet, EU zone 2' },
      { kind: 'removed', text: '€41.00 per pallet' },
      { kind: 'added', text: '€44.50 per pallet' },
      { kind: 'removed', text: 'Fuel surcharge 6%' },
      { kind: 'added', text: 'Fuel surcharge 7.5%' },
    ],
    history: [0, 1, 0, 0, 3, 0, 2],
  };
}
