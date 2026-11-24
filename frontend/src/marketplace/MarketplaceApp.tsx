// The marketplace shell. One rail, one main landmark, one polite route
// announcement. The route parser is pure; this component only chooses a
// page and moves focus to that page's heading.
import { useCallback, useEffect, useState } from 'react';
import Rail from '../dashboard/Rail';
import Button from '../components/Button';
import { SESSION_EXPIRED_MESSAGE, SESSION_EXPIRED_TITLE } from '../api';
import AdminPage from './Admin';
import { CatalogPage } from './CatalogPage';
import { onSessionExpired } from './client';
import { InstalledPage } from './Installed';
import { MarketLink, MarketplaceNavProvider } from './context';
import { PackPage } from './PackPage';
import { PluginDetailPage } from './PluginDetail';
import { PublisherPage, PublishersPage } from './Publishers';
import { routeTitle, useMarketplaceRouter, type MarketRoute } from './router';
import { StudioPage } from './Studio';
import TrustPage from './Trust';
import './marketplace.css';

/** Render one section tab as a marketplace link that marks the active page. */
function Tab({ to, current, children }: { to: string; current: boolean; children: string }) {
  return <MarketLink to={to} current={current} className="mkt-tab">{children}</MarketLink>;
}

/**
 * Render the two section tabs, lighting the one that owns the current route.
 *
 * Search and category results belong to Find plugins, and the manage view
 * belongs to Installed, so those routes keep their parent tab marked.
 * Publishers, Studio, Admin and the Trust center keep their addresses and
 * lose their links (spec 022): a person managing plugins needs two places.
 */
function Tabs({ route }: { route: MarketRoute }) {
  const find = ['discover', 'search', 'category'].includes(route.name);
  return (
    <nav className="mkt-tabs" aria-label="Plugins sections">
      <Tab to="/marketplace" current={find}>Find plugins</Tab>
      <Tab to="/marketplace/installed" current={route.name === 'installed' || route.name === 'manage'}>Installed</Tab>
    </nav>
  );
}

/**
 * Say the session expired, with the same words and the same one action the
 * dashboard uses: a fresh link from the shortcut is the only fix, so no
 * page-level retry is offered.
 */
function SessionNotice() {
  const focusHeading = useCallback((node: HTMLHeadingElement | null) => {
    node?.focus();
  }, []);
  return (
    <div className="mkt-page">
      <div className="mkt-error-panel" role="alert">
        <h1 ref={focusHeading} tabIndex={-1}>{SESSION_EXPIRED_TITLE}</h1>
        <p>{SESSION_EXPIRED_MESSAGE}</p>
        <Button tone="secondary" onClick={() => window.location.reload()}>Try again</Button>
      </div>
    </div>
  );
}

/** Render the 404 page for a path the route parser did not recognise. */
function NotFound({ path }: { path: string }) {
  return (
    <div className="mkt-page">
      <header className="mkt-page-head">
        <span className="mkt-eyebrow">404</span>
        <h1>Plugins page not found</h1>
        <p className="mkt-lede">There is no plugins page at {path}.</p>
      </header>
      <p><MarketLink className="btn btn-secondary" to="/marketplace">Find plugins</MarketLink></p>
    </div>
  );
}

/**
 * Render the page component for a parsed route.
 *
 * An unrecognised route falls through to the 404 page with its path intact,
 * so the message can name what was requested.
 */
function Page({ route }: { route: MarketRoute }) {
  switch (route.name) {
    case 'discover':
    case 'search':
    case 'category':
      return <CatalogPage route={route} />;
    case 'plugin':
      return <PluginDetailPage id={route.params.id} />;
    case 'manage':
      return <PluginDetailPage id={route.params.id} manage />;
    case 'pack':
      return <PackPage id={route.params.id} />;
    case 'installed':
      return <InstalledPage />;
    case 'publishers':
      return <PublishersPage />;
    case 'publisher':
      return <PublisherPage name={route.params.name} />;
    case 'studio':
      return <StudioPage />;
    case 'admin':
      return <AdminPage />;
    case 'trust':
      return <TrustPage />;
    default:
      return <NotFound path={route.params.path || '/marketplace'} />;
  }
}

/**
 * Render the marketplace shell: rail, section tabs, the page for the current
 * route, and a polite announcement of that route's title.
 *
 * The announcement is what tells a screen reader that navigation happened;
 * the document itself is never reloaded.
 */
export default function MarketplaceApp() {
  const { path, route, navigate } = useMarketplaceRouter();
  const [announcement, setAnnouncement] = useState('');
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    setAnnouncement(routeTitle(route));
  }, [path, route]);

  // Every marketplace call reports a 401 here. One notice replaces the
  // page, so no surface keeps a retry that would fail the same way.
  useEffect(() => onSessionExpired(() => setExpired(true)), []);

  return (
    <MarketplaceNavProvider value={{ path, navigate }}>
      <div className="app">
        <a className="skip-link" href="#marketplace-main">Skip to main content</a>
        <Rail inboxWaiting={0} active="/marketplace" />
        <main className="mkt-main" id="marketplace-main" tabIndex={-1}>
          <div className="mkt-sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>
          <Tabs route={route} />
          {expired ? <SessionNotice /> : <Page route={route} />}
        </main>
      </div>
    </MarketplaceNavProvider>
  );
}
