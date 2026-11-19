// The marketplace shell. One rail, one main landmark, one polite route
// announcement. The route parser is pure; this component only chooses a
// page and moves focus to that page's heading.
import { useEffect, useState } from 'react';
import Rail from '../dashboard/Rail';
import AdminPage from './Admin';
import { CatalogPage } from './CatalogPage';
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
 * Render the section tabs, lighting the one that owns the current route.
 *
 * Search and category results belong to Discover, and the manage view belongs
 * to Installed, so those routes keep their parent tab marked.
 */
function Tabs({ route }: { route: MarketRoute }) {
  const discover = ['discover', 'search', 'category'].includes(route.name);
  return (
    <nav className="mkt-tabs" aria-label="Marketplace sections">
      <Tab to="/marketplace" current={discover}>Discover</Tab>
      <Tab to="/marketplace/installed" current={route.name === 'installed' || route.name === 'manage'}>Installed</Tab>
      <Tab to="/marketplace/publishers" current={route.name === 'publishers' || route.name === 'publisher'}>Publishers</Tab>
      <Tab to="/marketplace/studio" current={route.name === 'studio'}>Studio</Tab>
    </nav>
  );
}

/** Render the 404 page for a path the route parser did not recognise. */
function NotFound({ path }: { path: string }) {
  return (
    <div className="mkt-page">
      <header className="mkt-page-head">
        <span className="mkt-eyebrow">404</span>
        <h1>Marketplace page not found</h1>
        <p className="mkt-lede">There is no marketplace surface at {path}.</p>
      </header>
      <p><MarketLink className="btn btn-secondary" to="/marketplace">Go to Discover</MarketLink></p>
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

  useEffect(() => {
    setAnnouncement(routeTitle(route));
  }, [path, route]);

  return (
    <MarketplaceNavProvider value={{ path, navigate }}>
      <div className="app">
        <a className="skip-link" href="#marketplace-main">Skip to main content</a>
        <Rail inboxWaiting={0} active="/marketplace" />
        <main className="mkt-main" id="marketplace-main" tabIndex={-1}>
          <div className="mkt-sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>
          <Tabs route={route} />
          <Page route={route} />
          <nav className="mkt-tabs mkt-footer-nav" aria-label="Marketplace administration">
            <Tab to="/marketplace/admin" current={route.name === 'admin'}>Admin</Tab>
            <Tab to="/marketplace/trust" current={route.name === 'trust'}>Trust center</Tab>
          </nav>
        </main>
      </div>
    </MarketplaceNavProvider>
  );
}
