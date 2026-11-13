// @vitest-environment node
// Dev-proxy completeness: in dev mode the vite server must hand every
// server-rendered page to the Python API, or a rail tab silently serves
// the dashboard shell again and the tab looks dead. These tests read
// vite.config.ts and the SPA's own link and call sets, so a future page
// or endpoint cannot be missed: they render nothing, they only read
// source files (the tokens tests' convention).
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, '..', '..');

const viteConfig = readFileSync(resolve(frontend, 'vite.config.ts'), 'utf8');
const rail = readFileSync(resolve(frontend, 'src', 'dashboard', 'Rail.tsx'), 'utf8');
const dashboard = readFileSync(resolve(frontend, 'src', 'dashboard', 'Dashboard.tsx'), 'utf8');

// The backendPaths array literal in vite.config.ts, with line comments
// stripped first so prose apostrophes cannot pose as quotes.
const pathsMatch = /const backendPaths = \[([\s\S]*?)\];/.exec(viteConfig);
const backendPaths = pathsMatch
  ? [...pathsMatch[1].replace(/^\s*\/\/.*$/gm, '').matchAll(/'([^']*)'|"([^"]*)"/g)]
      .map((m) => m[1] ?? m[2])
  : [];

// Every server-page href the rail and the dashboard footer carry.
function hrefsOf(source: string): string[] {
  return [...source.matchAll(/href=["']([^"']+)["']/g)].map((m) => m[1]);
}
const linkedHrefs = [...new Set([...hrefsOf(rail), ...hrefsOf(dashboard)])].filter((href) =>
  href.startsWith('/'),
);

// The plain-form action the dashboard posts to a server surface.
const formActions = [...dashboard.matchAll(/action=["']([^"']+)["']/g)]
  .map((m) => m[1])
  .filter((action) => action.startsWith('/'));

// The API targets the SPA calls: walk every source file (the test tree
// itself excluded, as the tokens walk does) and collect the string
// literals handed to getJson/postJson. Template-literal prefixes count
// up to the first ${.
function walkSources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === 'test') continue;
    const full = resolve(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walkSources(full));
    else if (/\.(ts|tsx)$/.test(entry)) out.push(full);
  }
  return out;
}
const apiTargets = walkSources(resolve(frontend, 'src'))
  .flatMap((file) => readFileSync(file, 'utf8').match(/\b(?:getJson|postJson)\((`[^`]*`|'[^']*'|"[^"]*")/g) ?? [])
  .map((call) => call.slice(call.indexOf('(') + 2, -1).split('${')[0]);

// Path constants the cards keep (WALKTHROUGH_PATH today): a named
// constant holding a /-literal is still a link the SPA makes to a
// server page, and the href scan above cannot see it. SCREAMING_CASE
// names only, so prose strings cannot sneak in.
const pathConstants = [
  ...new Set(
    walkSources(resolve(frontend, 'src', 'dashboard')).flatMap((file) =>
      [
        ...readFileSync(file, 'utf8').matchAll(
          /const\s+[A-Z][A-Z0-9_]*\s*=\s*(?:'([^']+)'|"([^"]+)")/g,
        ),
      ]
        .map((m) => m[1] ?? m[2])
        .filter((value) => value.startsWith('/')),
    ),
  ),
];

// The route the dev server serves itself: the SPA shell at /.
const SPA_ROUTES = ['/'];

function isProxied(target: string): boolean {
  return backendPaths.some((p) => target === p || target.startsWith(`${p}/`));
}

describe('the dev proxy covers every server page the SPA links to', () => {
  it('parses a non-empty backendPaths list from vite.config.ts', () => {
    expect(backendPaths.length).toBeGreaterThan(0);
  });

  // The guards below keep the it.each blocks honest: if a refactor
  // moves hrefs or actions behind constants the scans cannot read, the
  // collection empties and these named cases fail instead of the each
  // blocks quietly running zero cases and staying green.
  it('collects a non-empty set of rail and footer hrefs to check', () => {
    expect(linkedHrefs.length).toBeGreaterThan(0);
    expect(linkedHrefs).toContain('/settings');
  });

  it('collects the dashboard form actions to check', () => {
    expect(formActions.length).toBeGreaterThan(0);
    expect(formActions).toContain('/wizard/start');
  });

  it('collects the API call targets to check', () => {
    expect(new Set(apiTargets).size).toBeGreaterThan(0);
  });

  it('sees the card path constants the href scan cannot', () => {
    // CommitmentsCard keeps its walkthrough link behind a constant; the
    // scan must keep seeing it, or this pin has gone hollow.
    expect(pathConstants).toContain('/walkthrough/calendar');
  });

  it.each(linkedHrefs)('rail or footer href %s is served in dev mode', (href) => {
    expect(
      SPA_ROUTES.includes(href) || isProxied(href),
      `${href} is neither an SPA route nor listed in backendPaths; add it to vite.config.ts`,
    ).toBe(true);
  });

  it.each(formActions)('form action %s reaches the backend in dev mode', (action) => {
    expect(isProxied(action), `${action} is not listed in backendPaths`).toBe(true);
  });

  it.each([...new Set(apiTargets)])('API call %s reaches the backend in dev mode', (target) => {
    expect(isProxied(target), `${target} is not covered by any backendPaths prefix`).toBe(true);
  });

  it.each(pathConstants)('path constant %s is served in dev mode', (target) => {
    expect(
      SPA_ROUTES.includes(target) || isProxied(target),
      `${target} is neither an SPA route nor listed in backendPaths; add it to vite.config.ts`,
    ).toBe(true);
  });

  it('lists the five pages whose rail tabs were dead in dev mode', () => {
    for (const path of ['/plugins', '/activity', '/memory', '/mail', '/capabilities']) {
      expect(backendPaths, `${path} missing from backendPaths`).toContain(path);
    }
  });

  it('keeps the audit, walkthrough, what-this-touches and wizard surfaces proxied', () => {
    for (const path of ['/audit', '/walkthrough', '/what-this-touches', '/wizard']) {
      expect(backendPaths).toContain(path);
    }
  });
});
