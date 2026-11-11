// The composed empty state every card shares: one inset row with the
// icon inline beside the message and, when there is one, the action at
// the end of the same row (it wraps under the text on a narrow card).
// The card centers this row between its header and foot, so an empty
// card reads as a finished composition rather than a box in a void.
import type { ReactNode } from 'react';

interface EmptyStateProps {
  icon: ReactNode;
  children: ReactNode;
  action?: ReactNode;
}

const svg = (paths: ReactNode) => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    {paths}
  </svg>
);

export const ICON_SHEET = svg(
  <>
    <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
    <path d="M3.5 9.5h17M3.5 14.5h17M9.5 4.5v15" />
  </>,
);

export const ICON_CALENDAR = svg(
  <>
    <rect x="3.5" y="5.5" width="17" height="14" rx="2.5" />
    <path d="M3.5 10h17M8 3.5v4M16 3.5v4" />
  </>,
);

export const ICON_SEARCH = svg(
  <>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m16 16 4.5 4.5" />
  </>,
);

export default function EmptyState({ icon, children, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <span className="empty-icon" aria-hidden="true">{icon}</span>
      <p className="empty-text">{children}</p>
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
}
