// Presentation helpers: greeting, date line and freshness stamps,
// computed client-side from the raw timestamps the payload carries. The
// formats match the server-rendered cards exactly so both surfaces read
// the same.

export function greetingFor(now: Date): string {
  const hour = now.getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December',
];

const WEEKDAYS = [
  'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday',
];

export function dateLineFor(now: Date): string {
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  return `${WEEKDAYS[now.getDay()]}, ${now.getDate()} ${MONTHS[now.getMonth()]}, ${hh}:${mm}.`;
}

function hhmm(date: Date): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

export function hhmmFromTs(ts: number): string {
  return hhmm(new Date(ts * 1000));
}

export function hhmmFromIso(iso: string | null | undefined): string {
  if (!iso) return '';
  return hhmm(new Date(iso));
}

// The freshness contract of the sales card, from freshness_for in
// sales.py: stamp text only, the dot color is derived from fresh/attention.
export function salesStamp(
  state: string,
  lastOkTs: number | null | undefined,
): { fresh: boolean; text: string } {
  if (lastOkTs == null) return { fresh: false, text: 'Never polled' };
  const when = hhmmFromTs(lastOkTs);
  if (state === 'stale') return { fresh: false, text: `Stale since ${when}` };
  if (state === 'locked' || state === 'unreadable') {
    return { fresh: false, text: `Blocked, ${when}` };
  }
  if (state === 'first') return { fresh: true, text: `Snapshot ${when}` };
  return { fresh: true, text: `Updated ${when}` };
}

// The commitments stamp, from freshness_for in commitments.py.
export function commitmentsStamp(
  state: string,
  generatedAt: string | null | undefined,
): { fresh: boolean; text: string } {
  if (!generatedAt) return { fresh: false, text: 'No calendar data' };
  const when = hhmmFromIso(generatedAt);
  if (state === 'stale' || state === 'unreadable') {
    return { fresh: false, text: `Stale, ${when}` };
  }
  return { fresh: true, text: `Synced ${when}` };
}

// Cell value to display text: whole numbers grouped, text as is.
export function fmtCell(value: unknown): string {
  if (typeof value === 'number' && Number.isInteger(value)) {
    return value.toLocaleString('en-US');
  }
  return String(value);
}

// One example row on the sales card, from _row_line in sales.py.
export function rowLine(row: unknown[]): string {
  const cells = row.slice(0, 4).filter((v) => v !== '').map(fmtCell);
  return cells.length ? cells.join(' · ') : '(empty row)';
}

// Workbook file name from a path, as the card footer shows it.
export function fileNameOf(path: string | null | undefined): string {
  if (!path) return 'workbook';
  const normalized = path.replace(/\\/g, '/');
  return normalized.split('/').pop() || path;
}
