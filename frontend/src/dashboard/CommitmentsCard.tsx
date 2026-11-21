// The commitments card: healthy (key event, persisted subtask checks,
// followup chips), clear, empty (walkthrough link), stale and unreadable
// amber with Re-test, plus the disabled and unavailable branches. Copy
// and flows follow pages.py and commitments.py exactly; every card is
// the plain Card White article from the shared chrome.
import { useState, type KeyboardEvent } from 'react';
import { postJson } from '../api';
import { commitmentsStamp, hhmmFromIso } from '../fmt';
import type { CommitmentsStatus, KeyEvent } from '../types';
import WidgetCard from '../components/WidgetCard';
import Button from '../components/Button';
import EmptyState, { ICON_CALENDAR } from '../components/EmptyState';

const WALKTHROUGH_PATH = '/walkthrough/calendar';

interface CommitmentsCardProps {
  commitments: { enabled: boolean; mode: 'disabled' | 'unavailable' | 'live'; status: CommitmentsStatus | null };
  // The layout's custom title, when the user renamed the card.
  title?: string;
  onRefetch: () => Promise<void>;
  onExpired: () => void;
}

const CHECK_ON_SVG = (
  <span className="box" aria-hidden="true">
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  </span>
);

/** The key event's times, subject, location and attendee count. */
function KeyEventBlock({ event }: { event: KeyEvent }) {
  const start = new Date(event.start);
  const end = new Date(event.end);
  /** A date as a zero-padded 24-hour HH:MM clock time. */
  const fmt = (date: Date) =>
    `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  const whereParts: string[] = [];
  if (event.location) whereParts.push(event.location);
  if (event.attendees) whereParts.push(`${event.attendees} attendees`);
  return (
    <div className="event">
      <span className="when">{fmt(start)}<br />{fmt(end)}</span>
      <div>
        <b>{event.subject}</b>
        {whereParts.length > 0 ? <small>{whereParts.join(', ')}</small> : null}
      </div>
    </div>
  );
}

/**
 * One persisted subtask check, drawn as a checkbox and toggled by click, Space or
 * Enter.
 */
function CheckLine(props: { eventId: string; idx: number; text: string; checked: boolean; onToggle: () => void }) {
  const { eventId, idx, text, checked, onToggle } = props;
  /** Toggle the check when Space or Enter is pressed. */
  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      onToggle();
    }
  }
  return (
    <div
      className="check"
      role="checkbox"
      aria-checked={checked ? 'true' : 'false'}
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={onKey}
      data-event={eventId}
      data-idx={idx}
    >
      {CHECK_ON_SVG}
      <span>{text}</span>
    </div>
  );
}

/**
  * The calendar commitments card: the key event with its checks and follow-ups, or the
  * clear, empty, stale, unreadable, paused and unavailable branches.
 *
  * A click flips its box before the refetch answers, and the flip is dropped again when
  * the save fails. retest re-reads the calendar bridge; onExpired hands a 401 back to
  * the caller.
 */
export default function CommitmentsCard({ commitments, title, onRefetch, onExpired }: CommitmentsCardProps) {
  const status = commitments.status;
  const heading = title ?? "Today's key commitment";
  // Checks live in the payload; the click flips locally and persists
  // through the API, like the server-rendered card does. The local
  // flips are keyed by event and index and win over the payload, so the
  // box answers the click at once and stays right after the refetch.
  const [flips, setFlips] = useState<Record<string, boolean>>({});
  const [pendingNote, setPendingNote] = useState('');
  const [busy, setBusy] = useState(false);

  /** Re-test the calendar bridge and reload the dashboard. */
  async function retest() {
    setBusy(true);
    let res;
    try {
      res = await postJson('/sources/calendar-bridge/retest');
    } catch {
      setBusy(false);
      setPendingNote('The dashboard could not reach its own server; nothing changed.');
      return;
    }
    setBusy(false);
    if (res.status === 401) { onExpired(); return; }
    await onRefetch();
  }

  /**
   * Persist a check, answering the click locally first and dropping the flip when the
   * save fails.
   */
  function toggleCheck(eventId: string, idx: number, next: boolean) {
    // The click is the truth; the app persists it. No await: the flip is
    // instant, exactly like the server-rendered card.
    const key = `${eventId}:${idx}`;
    setFlips((prev) => ({ ...prev, [key]: next }));
    void postJson('/widgets/commitments/check', { eventId, idx, checked: next })
      .then((res) => {
        if (res.status === 401) { onExpired(); return undefined; }
        return onRefetch();
      })
      .catch(() => {
        // Nothing was saved, so the box goes back to what the server holds.
        setFlips((prev) => {
          const rest = { ...prev };
          delete rest[key];
          return rest;
        });
        setPendingNote('The dashboard could not reach its own server; the check was not saved.');
      });
  }

  if (commitments.mode === 'disabled') {
    return (
      <WidgetCard
        title={heading}
        span="span-5"
        footLines={2}
        sparse
        stamp={{ fresh: false, text: 'Paused' }}
        menuItems={[{ label: 'Open settings', href: '/settings' }]}
        foot="No ingestion while off."
      >
        <EmptyState
          icon={ICON_CALENDAR}
          action={<Button tone="primary" href="/settings">Turn it back on</Button>}
        >
          Calendar reading is turned off in settings. Your day is not being
          read right now.
        </EmptyState>
      </WidgetCard>
    );
  }

  if (commitments.mode === 'unavailable' || status === null) {
    return (
      <WidgetCard
        title={heading}
        span="span-5"
        footLines={2}
        sparse
        stamp={{ fresh: false, text: 'Unavailable' }}
        menuItems={[{ label: 'Open settings', href: '/settings' }]}
        foot="Nothing is being read while the bridge is unavailable."
      >
        <EmptyState icon={ICON_CALENDAR}>
          The calendar bridge is not running on this machine, so today's
          commitments cannot be read. Restarting Nexuus Bot usually brings it
          back.
        </EmptyState>
      </WidgetCard>
    );
  }

  const stamp = commitmentsStamp(status.state, status.generatedAt);
  const first = status.firstDetected ? hhmmFromIso(status.firstDetected) : null;

  if (status.state === 'healthy' && status.keyEvent) {
    const breakdown = status.breakdown ?? { subtasks: [], followups: [] };
    const checks = status.checks ?? {};
    const eventId = status.keyEvent.id;
    /**
     * The box state for a subtask: the local flip when there is one, else the server's
     * payload.
     */
    const isChecked = (idx: number) => flips[`${eventId}:${idx}`] ?? Boolean(checks[String(idx)]);
    return (
      <WidgetCard
        title={heading}
        span="span-5"
        footLines={2}
        stamp={stamp}
        menuItems={[
          { label: 'Re-test now', onSelect: retest, disabled: busy },
          { label: 'Open settings', href: '/settings' },
        ]}
        foot={`From your calendar via the OneDrive sync. Nothing leaves the machine but the meeting's name.${first ? ` Connected ${first}.` : ''}`}
      >
        <KeyEventBlock event={status.keyEvent} />
        <div>
          <div className="subhead subhead-tight">Agent's breakdown</div>
          {(breakdown.subtasks ?? []).map((text, idx) => (
            <CheckLine
              key={`${eventId}-${idx}`}
              eventId={eventId}
              idx={idx}
              text={text}
              checked={isChecked(idx)}
              onToggle={() => toggleCheck(eventId, idx, !isChecked(idx))}
            />
          ))}
        </div>
        {(breakdown.followups ?? []).map((followup, idx) => (
          <span className="follow" key={`f${idx}`}>
            {followup.text}
            {followup.deadline ? `, by ${followup.deadline}` : ''}
          </span>
        ))}
        {pendingNote ? <div className="alert" role="status">{pendingNote}</div> : null}
      </WidgetCard>
    );
  }

  if (status.state === 'clear') {
    return (
      <WidgetCard
        title={heading}
        span="span-5"
        footLines={2}
        sparse
        stamp={stamp}
        menuItems={[
          { label: 'Re-test now', onSelect: retest, disabled: busy },
          { label: 'Open settings', href: '/settings' },
        ]}
        foot="From your calendar via the OneDrive sync."
      >
        <EmptyState icon={ICON_CALENDAR}>
          Your calendar is clear for the rest of today. Nothing needs
          preparing.
        </EmptyState>
      </WidgetCard>
    );
  }

  if (status.state === 'empty') {
    return (
      <WidgetCard
        title={heading}
        span="span-5"
        footLines={2}
        sparse
        stamp={stamp}
        menuItems={[
          { label: 'Connect your calendar', href: WALKTHROUGH_PATH },
          { label: 'Open settings', href: '/settings' },
        ]}
        foot="Setup happens in your browser. No terminal, no admin."
      >
        <EmptyState
          icon={ICON_CALENDAR}
          action={<Button tone="primary" href={WALKTHROUGH_PATH}>Connect your calendar</Button>}
        >
          No calendar data yet. Nexuus Bot watches{' '}
          <code className="nowrap">agent-desk/calendar_sync.json</code>
          {' '}in your OneDrive. A 3-step browser walkthrough creates the flow
          that writes it.
        </EmptyState>
      </WidgetCard>
    );
  }

  if (status.state === 'stale') {
    return (
      <WidgetCard
        title={heading}
        span="span-5"
        footLines={2}
        sparse
        stamp={stamp}
        amber
        menuItems={[
          { label: 'Re-test now', onSelect: retest, disabled: busy },
          { label: 'Open the walkthrough', href: WALKTHROUGH_PATH },
          { label: 'Open settings', href: '/settings' },
        ]}
        foot="Stale data is labeled, never shown as current."
      >
        <div className="alert" role="status"><span>{status.cause}</span></div>
        <Button className="btn-start" onClick={retest} disabled={busy}>Re-test now</Button>
        <Button className="btn-start" href={WALKTHROUGH_PATH}>Open the walkthrough</Button>
        {pendingNote ? <div className="alert" role="status">{pendingNote}</div> : null}
      </WidgetCard>
    );
  }

  // unreadable
  return (
    <WidgetCard
      title={heading}
      span="span-5"
      footLines={2}
      sparse
      stamp={stamp}
      amber
      menuItems={[
        { label: 'Re-test now', onSelect: retest, disabled: busy },
        { label: 'Open settings', href: '/settings' },
      ]}
      foot="The file is there but not readable as calendar data."
    >
      <div className="alert" role="status"><span>{status.cause}</span></div>
      <Button className="btn-start" onClick={retest} disabled={busy}>Re-test now</Button>
      {pendingNote ? <div className="alert" role="status">{pendingNote}</div> : null}
    </WidgetCard>
  );
}
