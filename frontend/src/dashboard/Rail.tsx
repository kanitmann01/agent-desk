// The rail: brand, the four entries, the inbox count badge and the user
// line, matching the server-rendered rail entry for entry. Plugins stays
// switched off until a plugins page exists; every other entry is a real
// server page. Drawn as a floating glass column; the app name carries
// the cyan to violet gradient through the vendored GradientText.
import GradientText from '../vendor/reactbits/GradientText';

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
        <GradientText
          className="brand-name"
          colors={['#22D3EE', '#8B5CF6', '#22D3EE']}
          animationSpeed={7}
        >
          Agent Desk
        </GradientText>
      </div>
      <a href="/" aria-current="page">{ICON_DASHBOARD}Dashboard</a>
      <a href="/inbox">{ICON_INBOX}Inbox{badge}</a>
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
