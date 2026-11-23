// A pure route parser plus the smallest history hook the SPA needs.
// No router dependency: parseRoute is a pure function, and the hook adds
// pushState/popstate so back, forward and a refresh on a deep link work.
import { useCallback, useEffect, useMemo, useState } from 'react';

export type RouteName =
  | 'discover'
  | 'search'
  | 'category'
  | 'plugin'
  | 'manage'
  | 'pack'
  | 'installed'
  | 'publishers'
  | 'publisher'
  | 'studio'
  | 'admin'
  | 'trust'
  | 'notfound';

export interface MarketRoute {
  name: RouteName;
  params: Record<string, string>;
}

/**
 * Decode one path segment, returning it unchanged when it holds a malformed
 * escape rather than failing the whole route.
 */
function decode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/** Build the catch-all route, keeping the unparsed path for display. */
function notFound(path: string): MarketRoute {
  return { name: 'notfound', params: { path } };
}

/** Parse a pathname, optionally with a query string, into a route. */
export function parseRoute(input: string): MarketRoute {
  const raw = (input || '/').split('#')[0];
  const queryAt = raw.indexOf('?');
  const rawPath = queryAt >= 0 ? raw.slice(0, queryAt) : raw;
  const rawQuery = queryAt >= 0 ? raw.slice(queryAt + 1) : '';
  const query = new URLSearchParams(rawQuery);
  let path = rawPath || '/';
  if (!path.startsWith('/')) path = '/' + path;
  if (path.length > 1) path = path.replace(/\/+$/, '');
  const segments = path.split('/').filter(Boolean);
  if (segments[0] !== 'marketplace') return notFound(path);
  const rest = segments.slice(1);
  if (rest.length === 0) return { name: 'discover', params: {} };
  const [head, second, third] = rest;
  if (rest.length === 1) {
    if (head === 'search') {
      return { name: 'search', params: { q: query.get('q') ?? '' } };
    }
    if (head === 'installed') return { name: 'installed', params: {} };
    if (head === 'publishers') return { name: 'publishers', params: {} };
    if (head === 'studio') return { name: 'studio', params: {} };
    if (head === 'admin') return { name: 'admin', params: {} };
    if (head === 'trust') return { name: 'trust', params: {} };
    return notFound(path);
  }
  if (rest.length === 2) {
    if (head === 'category' && second) {
      return { name: 'category', params: { category: decode(second) } };
    }
    if (head === 'plugin' && second) {
      return { name: 'plugin', params: { id: decode(second) } };
    }
    if (head === 'pack' && second) {
      return { name: 'pack', params: { id: decode(second) } };
    }
    if (head === 'publisher' && second) {
      return { name: 'publisher', params: { name: decode(second) } };
    }
    if (head === 'manage' && second) {
      return { name: 'manage', params: { id: decode(second) } };
    }
    return notFound(path);
  }
  if (rest.length === 3 && head === 'plugin' && second && third === 'manage') {
    return { name: 'manage', params: { id: decode(second) } };
  }
  return notFound(path);
}

/**
 * Return the document title for a route, filling in the name or category its
 * params carry where the route name alone is too generic.
 */
export function routeTitle(route: MarketRoute): string {
  switch (route.name) {
    case 'discover': return 'Plugins';
    case 'search': return 'Plugins search';
    case 'category': return `${route.params.category} plugins`;
    case 'plugin': return 'Plugin details';
    case 'manage': return 'Manage plugin';
    case 'pack': return 'Pack details';
    case 'installed': return 'Installed plugins';
    case 'publishers': return 'Publishers';
    case 'publisher': return route.params.name;
    case 'studio': return 'Plugin Studio';
    case 'admin': return 'Marketplace admin';
    case 'trust': return 'Trust center';
    default: return 'Plugins page not found';
  }
}

/**
 * Read the address bar's path and query.
 *
 * Without a window (server rendering, tests) it answers the discover path so
 * the hook has a usable location before the first effect runs.
 */
function currentLocation(): string {
  if (typeof window === 'undefined') return '/marketplace';
  return window.location.pathname + window.location.search;
}

/**
 * Track the current location and expose a navigate that writes history.
 *
 * Popstate keeps back, forward and a deep-link refresh in sync. Navigating to
 * the location already shown is a no-op, so a repeated click adds no history
 * entry.
 */
export function useMarketplaceRouter() {
  const [path, setPath] = useState(currentLocation);
  useEffect(() => {
    /** Follow the browser through history so back, forward and a refresh keep the path in sync. */
    const onPop = () => setPath(currentLocation());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  const navigate = useCallback((to: string, replace = false) => {
    const target = to.startsWith('/') ? to : `/${to}`;
    if (target === currentLocation()) return;
    if (replace) window.history.replaceState({}, '', target);
    else window.history.pushState({}, '', target);
    setPath(target);
  }, []);
  const route = useMemo(() => parseRoute(path), [path]);
  return { path, route, navigate };
}
