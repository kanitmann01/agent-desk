// The rail: brand, the entries, the inbox count badge, the collapse
// control and the user line. Dashboard, Inbox, Assistant and Settings
// are real server pages (GET /inbox, /assistant, /settings); so are the
// four consolidation pages (GET /activity, /memory, /mail,
// /capabilities), the plugins page (GET /plugins) and the peers page
// (GET /peers). Drawn as the system's full-height Input Well column;
// the brand is plain text in the ink. Each entry's label rides in a
// .rail-label span so collapse can drop the words and keep the marks.
// The collapsed state persists in localStorage and mirrors the
// server-rendered pages' toggle (key: agentdesk.railCollapsed).
import { useEffect, useState } from 'react';

interface RailProps {
  inboxWaiting: number;
  active?: string;
}

const RAIL_KEY = 'agentdesk.railCollapsed';

function storedCollapsed(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === '1';
  } catch {
    return false;
  }
}

const ICON_DASHBOARD = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
    <rect x="3.5" y="3.5" width="7" height="7" rx="2" />
    <rect x="13.5" y="3.5" width="7" height="7" rx="2" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="2" />
    <rect x="13.5" y="13.5" width="7" height="7" rx="2" />
  </svg>
);

const ICON_INBOX = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3.5 13.5 5 20h14l1.5-6.5M3.5 13.5h17M12 15v-4" />
  </svg>
);

const ICON_ASSISTANT = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 5.5h14a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5h-6.5L8 20.5v-4H5A1.5 1.5 0 0 1 3.5 15V7A1.5 1.5 0 0 1 5 5.5Z" />
    <path d="M8.5 10h7M8.5 13h4" />
  </svg>
);

const ICON_PLUGINS = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
    <rect x="3.5" y="3.5" width="17" height="17" rx="4" />
    <path d="M12 8v8M8 12h8" />
  </svg>
);

const ICON_SETTINGS = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
    <path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3" />
    <circle cx="15" cy="7" r="2" />
    <circle cx="9" cy="12" r="2" />
    <circle cx="15" cy="17" r="2" />
  </svg>
);

const ICON_ACTIVITY = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3.5 12h4l2.5-6.5 4 13 2.5-6.5h4" />
  </svg>
);

const ICON_MEMORY = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <ellipse cx="12" cy="5.5" rx="7.5" ry="2.5" />
    <path d="M4.5 5.5v13c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5v-13" />
    <path d="M4.5 12c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5" />
  </svg>
);

const ICON_MAIL = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3.5" y="5.5" width="17" height="13" rx="2" />
    <path d="m4.5 8 7.5 5.5L19.5 8" />
  </svg>
);

const ICON_CAPABILITIES = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3.5 5 6.2v4.6c0 4.6 3 8.6 7 9.7 4-1.1 7-5.1 7-9.7V6.2L12 3.5Z" />
    <path d="m9 11.5 2.2 2.2 3.8-4.4" />
  </svg>
);

const ICON_PEERS = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="8" cy="8" r="3" />
    <circle cx="16" cy="16" r="3" />
    <path d="M10.5 10.5 13.5 13.5" />
    <path d="M3.5 8h1.5M19 16h1.5" />
  </svg>
);

export default function Rail({ inboxWaiting, active = '/' }: RailProps) {
  const badge = inboxWaiting > 0 ? <span className="count">{inboxWaiting}</span> : null;
  const [collapsed, setCollapsed] = useState(storedCollapsed);
  // The accessible name survives collapse: the visible label hides with
  // the wide rail, so every link carries its own aria-label, and the
  // Inbox link names its waiting count.
  const inboxName = inboxWaiting > 0 ? `Inbox, ${inboxWaiting} waiting` : 'Inbox';

  // The class lands on the .app shell, exactly where the stylesheet's
  // collapsed rules read it; the server pages do the same in app.js.
  useEffect(() => {
    const app = document.querySelector('.app');
    if (app) app.classList.toggle('rail-collapsed', collapsed);
  }, [collapsed]);

  function toggle() {
    setCollapsed((current) => {
      const next = !current;
      try {
        localStorage.setItem(RAIL_KEY, next ? '1' : '0');
      } catch {
        // Storage unavailable (private mode): the toggle still works
        // for this session.
      }
      return next;
    });
  }

  return (
    <nav className="rail" aria-label="Main">
      <div className="brand">
        <span className="mark" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2.4" strokeLinecap="round">
            <path d="M4 12h6M8 8v8M14 10h6M17 7v10" />
          </svg>
        </span>
        <span className="brand-name">Agent Desk</span>
      </div>
      <a href="/" aria-current={active === '/' ? 'page' : undefined} aria-label="Dashboard">{ICON_DASHBOARD}<span className="rail-label">Dashboard</span></a>
      <a href="/inbox" aria-label={inboxName}>{ICON_INBOX}<span className="rail-label">Inbox</span>{badge}</a>
      <a href="/assistant" aria-label="Assistant">{ICON_ASSISTANT}<span className="rail-label">Assistant</span></a>
      <a href="/activity" aria-label="Activity">{ICON_ACTIVITY}<span className="rail-label">Activity</span></a>
      <a href="/memory" aria-label="Memory">{ICON_MEMORY}<span className="rail-label">Memory</span></a>
      <a href="/mail" aria-label="Mail">{ICON_MAIL}<span className="rail-label">Mail</span></a>
      <a href="/capabilities" aria-label="Capabilities">{ICON_CAPABILITIES}<span className="rail-label">Capabilities</span></a>
      <a href="/marketplace" aria-current={active.startsWith('/marketplace') ? 'page' : undefined} aria-label="Marketplace">{ICON_PLUGINS}<span className="rail-label">Marketplace</span></a>
      <a href="/peers" aria-label="Peers">{ICON_PEERS}<span className="rail-label">Peers</span></a>
      <a href="/settings" aria-label="Settings">{ICON_SETTINGS}<span className="rail-label">Settings</span></a>
      <button
        type="button"
        className="rail-toggle"
        aria-expanded={!collapsed}
        aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
        onClick={toggle}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
          <path d="M14.5 6.5 8 12l6.5 5.5" />
        </svg>
        <span className="rail-toggle-label">Collapse</span>
      </button>
      <div className="user">
        <span className="avatar" aria-hidden="true">AD</span>
        <div>
          <b className="user-name">Agent Desk</b>
          <small>local only</small>
        </div>
      </div>
    </nav>
  );
}
