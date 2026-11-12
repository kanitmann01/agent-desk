// The rail: brand, the entries, the inbox count badge and the user
// line. Dashboard, Inbox, Assistant and Settings are real server pages
// (GET /inbox, /assistant, /settings); Plugins stays switched off until
// a plugins page exists. Drawn as the system's full-height Input Well
// column; the brand is plain text in the ink.
interface RailProps {
  inboxWaiting: number;
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

export default function Rail({ inboxWaiting }: RailProps) {
  const badge = inboxWaiting > 0 ? <span className="count">{inboxWaiting}</span> : null;
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
      <a href="/" aria-current="page">{ICON_DASHBOARD}Dashboard</a>
      <a href="/inbox">{ICON_INBOX}Inbox{badge}</a>
      <a href="/assistant">{ICON_ASSISTANT}Assistant</a>
      <span className="nav-off" aria-disabled="true" title="Arrives in a later build">
        {ICON_PLUGINS}Plugins
      </span>
      <a href="/settings">{ICON_SETTINGS}Settings</a>
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
