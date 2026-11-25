// The rail: brand, the entries, the inbox count badge, the collapse
// control and the user line. Dashboard, Inbox, Assistant, Agents and
// Settings are real server pages (GET /inbox, /assistant, /agents,
// /settings); so are the four consolidation pages (GET /activity,
// /memory, /mail, /capabilities), the plugins page (GET /plugins) and
// the peers page (GET /peers). Drawn as the system's full-height
// Input Well column;
// the brand is plain text in the ink. Each entry's label rides in a
// .rail-label span so collapse can drop the words and keep the marks.
// The collapsed state persists in localStorage and mirrors the
// server-rendered pages' toggle (key: agentdesk.railCollapsed).
import { useEffect, useState } from 'react';
import FaceSlot from '../face/FaceSlot';
import ThemePicker from '../theme/ThemePicker';

interface RailProps {
  inboxWaiting: number;
  active?: string;
}

const RAIL_KEY = 'agentdesk.railCollapsed';

/** The persisted rail collapse state, false when storage is unavailable. */
function storedCollapsed(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === '1';
  } catch {
    return false;
  }
}

/**
  * The main navigation rail: brand, entries, inbox badge, theme picker and collapse
  * control.
 *
  * active is the current route, which drives aria-current and the phone bar's section
  * name; inboxWaiting is the inbox count behind the badge.
 */
export default function Rail({ inboxWaiting, active = '/' }: RailProps) {
  const badge = inboxWaiting > 0 ? <span className="count">{inboxWaiting}</span> : null;
  const [collapsed, setCollapsed] = useState(storedCollapsed);
  const [menuOpen, setMenuOpen] = useState(false);
  const sectionName = active.startsWith('/marketplace') ? 'Plugins'
    : active === '/inbox' ? 'Inbox'
    : active === '/assistant' ? 'Assistant'
    : active === '/agents' ? 'Agents'
    : active === '/settings' ? 'Settings'
    : 'Dashboard';
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

  /**
   * Flip the rail between collapsed and expanded, persisting the choice for the next
   * page.
   */
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
    <nav id="main-rail" className={menuOpen ? 'rail rail-open' : 'rail'} aria-label="Main">
      <div className="phone-bar">
        <span className="brand-name">Agent Desk</span>
        <span className="phone-current">{sectionName}</span>
        <button
          type="button"
          className="phone-menu"
          aria-expanded={menuOpen}
          aria-controls="main-rail"
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? 'Close' : 'Menu'}
        </button>
      </div>
      <div className="brand">
        <FaceSlot slot="rail" />
        <span className="brand-name">Agent Desk</span>
      </div>
      <a href="/" title="Dashboard" aria-current={active === '/' ? 'page' : undefined} aria-label="Dashboard"><span className="rail-mark" aria-hidden="true">D</span><span className="rail-label">Dashboard</span></a>
      <a href="/inbox" title={inboxName} aria-label={inboxName}><span className="rail-mark" aria-hidden="true">I</span><span className="rail-label">Inbox</span>{badge}</a>
      <a href="/assistant" title="Assistant" aria-label="Assistant"><span className="rail-mark" aria-hidden="true">A</span><span className="rail-label">Assistant</span></a>
      {/* Agents beside Assistant: both are host surfaces over the one
          endpoint, one per question, one per task. A server page like
          Assistant, so the SPA rail never marks it current. */}
      <a href="/agents" title="Agents" aria-label="Agents"><span className="rail-mark" aria-hidden="true">A</span><span className="rail-label">Agents</span></a>
      <a href="/memory" title="Memory" aria-label="Memory"><span className="rail-mark" aria-hidden="true">M</span><span className="rail-label">Memory</span></a>
      <a href="/mail" title="Mail" aria-label="Mail"><span className="rail-mark" aria-hidden="true">M</span><span className="rail-label">Mail</span></a>
      {/* The marketplace is the Plugins page (spec 022): a person looks for
          their plugins, not a shop. The address is unchanged. */}
      <a href="/marketplace" title="Plugins" aria-current={active.startsWith('/marketplace') ? 'page' : undefined} aria-label="Plugins"><span className="rail-mark" aria-hidden="true">P</span><span className="rail-label">Plugins</span></a>
      {/* Activity, Capabilities and Peers live under Settings now: the
          rail carries the daily surfaces, not every route. */}

      <a href="/settings" title="Settings" aria-label="Settings"><span className="rail-mark" aria-hidden="true">S</span><span className="rail-label">Settings</span></a>
      <button
        type="button"
        className="rail-toggle"
        aria-expanded={!collapsed}
        aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
        title={collapsed ? 'Expand navigation' : 'Collapse navigation'}
        onClick={toggle}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
          <path d="M14.5 6.5 8 12l6.5 5.5" />
        </svg>
        <span className="rail-toggle-label">Collapse</span>
      </button>
      <div className="rail-theme">
        <span className="rail-theme-label">Theme</span>
        <ThemePicker compact />
      </div>
      <div className="user">
        <span className="avatar" aria-hidden="true" title="Agent Desk">AD</span>
        <div>
          <b className="user-name">Agent Desk</b>
          <small>local only</small>
        </div>
      </div>
    </nav>
  );
}
