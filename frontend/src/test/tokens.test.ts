// @vitest-environment node
// The design-contract suite: the stylesheet, the shell HTML, the package
// manifest and the license records must speak the warm-paper system from
// DESIGN.md (docs/design-language.md), and must not carry any of the
// recorded dark-glass drift. These tests read files; they render nothing.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, '..', '..');
const repo = resolve(frontend, '..');

const css = readFileSync(resolve(frontend, 'src/index.css'), 'utf8');
const marketCss = readFileSync(resolve(frontend, 'src/marketplace/marketplace.css'), 'utf8');
const adminCss = readFileSync(resolve(frontend, 'src/marketplace/admin-trust.css'), 'utf8');
const html = readFileSync(resolve(frontend, 'index.html'), 'utf8');
const pkg = JSON.parse(readFileSync(resolve(frontend, 'package.json'), 'utf8')) as {
  dependencies: Record<string, string>;
  devDependencies: Record<string, string>;
  scripts: Record<string, string>;
};
const manifest = readFileSync(resolve(repo, 'THIRD-PARTY-LICENSES.md'), 'utf8');
const licenses = readdirSync(resolve(frontend, 'public', 'licenses'));

// The committed bundle stylesheet, wherever the build put it.
const spaAssets = resolve(repo, 'src', 'agentdesk', 'server', 'static', 'spa', 'assets');
const bundleCss = readdirSync(spaAssets)
  .filter((f) => f.endsWith('.css'))
  .map((f) => readFileSync(resolve(spaAssets, f), 'utf8'))
  .join('\n');
const bundleJs = readdirSync(spaAssets)
  .filter((f) => f.endsWith('.js'))
  .map((f) => readFileSync(resolve(spaAssets, f), 'utf8'))
  .join('\n');

// Component sources walk: every .ts/.tsx under src/ except the test
// tree itself.
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
const sources = walkSources(resolve(frontend, 'src'))
  .map((f) => readFileSync(f, 'utf8'))
  .join('\n');

// The shared card chrome lives in src/components; nothing there may
// reach into the vendored effects drawer.
const componentSources = walkSources(resolve(frontend, 'src', 'components'))
  .map((f) => readFileSync(f, 'utf8'))
  .join('\n');

// The fourteen DESIGN.md frontmatter colors, each asserted as the exact
// hex so a near-miss (a re-darkened green, a colder paper) fails.
const SYSTEM_COLORS: Array<[string, string]> = [
  ['canvas', '#060609'],
  ['cell', '#101014'],
  ['rule', '#26272A'],
  ['text', '#FBFBFB'],
  ['muted', '#8E8E93'],
  ['highlighter', '#E1F56A'],
];

// The recorded dark-glass drift palette: none of it may survive.
const DRIFT_COLORS = [
  '#020617',
  '#0E1223',
  '#22C55E',
  '#4ADE80',
  '#22D3EE',
  '#8B5CF6',
  '#F59E0B',
  '#F87171',
  '#334155',
  '#F8FAFC',
];

const CARD_AT_REST = '--shadow-card:none';
const CARD_LIFTED = '--shadow-card-hover:none';

describe('index.css speaks the warm-paper system', () => {
  it('carries every DESIGN.md color token', () => {
    for (const [name, hex] of SYSTEM_COLORS) {
      expect(css, `missing ${name} ${hex}`).toContain(hex);
    }
  });

  it('carries none of the dark-glass drift palette', () => {
    for (const hex of DRIFT_COLORS) {
      expect(css, `drift color survived: ${hex}`).not.toContain(hex);
    }
  });

  it('declares color-scheme dark', () => {
    expect(css).toContain('color-scheme: dark');
  });

  it('sets the paper-lift shadows as the only depth', () => {
    expect(css).toContain(CARD_AT_REST);
    expect(css).toContain(CARD_LIFTED);
  });

  it('bans every glass, glow and gradient effect', () => {
    for (const banned of [
      'backdrop-filter',
      'conic-gradient',
      'linear-gradient',
      'text-shadow',
      'drop-shadow',
      '@property',
      'blur(',
    ]) {
      expect(css, `banned effect survived: ${banned}`).not.toContain(banned);
    }
  });

  it('allows one radial light, monochrome, on the Unkey hero only', () => {
    const radials = css.match(/radial-gradient\([^;]*\);/g) ?? [];
    expect(radials).toHaveLength(1);
    expect(radials[0]).toMatch(/^radial-gradient\(ellipse [^;]*rgb\(255 255 255 \/ \.\d+\),rgb\(255 255 255 \/ 0\)\);$/);
    expect(css).toContain(`--hero-light:${radials[0]}`);
    expect(css.match(/--hero-light:none;/g)).toHaveLength(2);
    expect(marketCss).not.toContain('gradient');
  });

  it('sets numerals in Geist Mono and words in Geist', () => {
    expect(css).toContain('"Geist Mono"');
    expect(css).toContain('tabular-nums');
    expect(css).toContain('"Geist"');
    expect(css).not.toContain('Plus Jakarta Sans');
    expect(css).not.toContain('Source Serif 4');
  });

  it('imports only the system fonts, self-hosted', () => {
    expect(css).toContain('@fontsource/geist/400.css');
    expect(css).toContain('@fontsource/geist-mono/400.css');
    expect(css).not.toContain('@fontsource-variable/plus-jakarta-sans');
    expect(css).not.toContain('@fontsource-variable/inter');
    expect(css).not.toContain('@fontsource-variable/space-grotesk');
  });

  it('uses the concentric radii and the full-round pill', () => {
    expect(css).toContain('--r-card:8px');
    expect(css).toContain('--r-control:6px');
    expect(css).toContain('--r-inner:4px');
    expect(css).not.toContain('999px');
  });

  it('uses the 200px rail beside a 1200px content column', () => {
    expect(css).toContain('grid-template-columns:200px');
    expect(css).toContain('max-width:1200px');
    expect(css).toContain('28px 36px 60px');
  });

  it('sets the greeting at 40px and the one figure at 56px', () => {
    expect(css).not.toContain('clamp(');
    expect(css).toContain('font-size:40px');
    expect(css).toContain('font-size:56px');
    expect(css).not.toContain('font-size:64px');
  });

  it('still freezes animation under prefers-reduced-motion', () => {
    expect(css).toContain('@media (prefers-reduced-motion:reduce)');
  });
});

describe('the SPA shell declares the light paper world', () => {
  it('declares color-scheme light and the paper theme color', () => {
    expect(html).toContain('content="dark"');
    expect(html).toContain('#060609');
    expect(html).not.toContain('#020617');
    expect(html).not.toContain('content="light"');
  });
});

describe('component sources speak the system inks', () => {
  // The dark-glass theme hardcoded pastel paints (ShinyText, GradientText,
  // glare sweeps, the status mark) that are near-invisible on paper. No
  // component may pass a drift color; effects carry system tokens or die
  // with the components tickets.
  it('carries none of the drift paints', () => {
    const driftPaints = [
      '#B6C0D2',
      '#D5DDE9',
      '#8FD8F2',
      '#B3AEF5',
      '#7DD3FC',
      '#A5B4FC',
      '#F8FAFC',
      '#F0FFF6',
      '#22C55E',
      '#F59E0B',
    ];
    for (const hex of driftPaints) {
      expect(sources, `drift paint survived in src: ${hex}`).not.toContain(hex);
    }
  });

  it('builds on no vendored effects: the drawer is gone', () => {
    expect(existsSync(resolve(frontend, 'src', 'vendor'))).toBe(false);
    expect(componentSources, 'src/components imports a vendored drawer').not.toContain(
      'vendor/reactbits',
    );
  });
});

describe('the authored sheet keeps its interaction promises', () => {
  it('sets the command bar field at body size', () => {
    expect(decl(css, '.cmd-field', 'font')).toContain('14px');
  });

  it('gives the command bar field a visible focus ring', () => {
    expect(css).toContain(':focus-visible{outline:2px solid var(--focus)');
    expect(css).not.toContain('.cmd-field:focus{outline:none');
  });

  it('folds Research into an icon button inside the field on small screens', () => {
    expect(css).toContain('.cmd-magnet{flex:none;display:flex}');
    expect(css).toContain('.cmd-send-label{');
  });
});

// The text of one media query, balanced to its closing brace, so
// contract tests can pin what the narrow-width world does.
function mediaBlock(text: string, query: string): string {
  const marker = `@media (${query}){`;
  const start = text.indexOf(marker);
  if (start === -1) return '';
  let depth = 0;
  for (let i = start + marker.length - 1; i < text.length; i += 1) {
    if (text[i] === '{') depth += 1;
    else if (text[i] === '}') {
      depth -= 1;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return '';
}

// The server-rendered pages carry their own copy of the shell CSS; both
// must agree, so the tests read it out of the Python source.
const serverPages = readFileSync(
  resolve(repo, 'src', 'agentdesk', 'server', 'pages.py'),
  'utf8',
);
const serverStylesMatch = /STYLES = """(.*?)"""/s.exec(serverPages);
const serverStyles = serverStylesMatch ? serverStylesMatch[1] : '';

describe('the rail stays on screen at every width', () => {
  it.each([
    ['the SPA sheet', css],
    ['the server sheet', serverStyles],
  ])('%s keeps the narrow-width rail pinned and wrapping', (_name, sheet) => {
    const narrow = mediaBlock(sheet, 'max-width:980px');
    expect(narrow, 'no 980px media block').not.toBe('');
    const railRule = narrow.match(/\.rail\{[^}]*\}/)?.[0] ?? '';
    expect(railRule, 'narrow rail must stay sticky').toContain('position:sticky;top:0');
    expect(railRule, 'narrow rail must release the desktop full height').toContain('height:auto');
    expect(railRule, 'narrow rail entries must wrap, not clip').toContain('flex-wrap:wrap');
    expect(railRule, 'narrow rail must not scroll sideways').not.toContain('overflow-x');
    expect(railRule, 'sticky strip must paint above the content').toContain('z-index');
    expect(narrow, 'narrow rail opens from a menu bar').toContain('.phone-bar{display:flex');
    expect(narrow, 'narrow rail targets are 44px').toContain('min-height:44px');
    expect(narrow, 'focused content clears the sticky strip').toContain('scroll-padding-top:64px');
    // Sticky inside its own auto-sized grid row has no travel: the
    // single-column shell must become a block for the pin to work.
    expect(narrow, 'single-column shell must become a block').toContain('.app{display:block}');
  });

  it('keeps a nowrap helper and stacks the hero source line on narrow screens', () => {
    expect(css).toContain('.nowrap{white-space:nowrap}');
    const narrow = mediaBlock(css, 'max-width:560px');
    expect(narrow, 'no 560px media block').not.toBe('');
    expect(narrow).toContain('.hero-live');
    expect(narrow).toContain('width:100%');
  });
});

// The value of one declaration inside a rule, so contract tests can pin
// exact spacing values without reimplementing CSS parsing.
function decl(text: string, selector: string, property: string): string {
  const rule = text.match(new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\{([^}]*)\\}`))?.[1] ?? '';
  const m = rule.match(new RegExp(`${property}\\s*:\\s*([^;]+)`));
  return m ? m[1].trim() : '';
}

function onGrid(value: string): boolean {
  // Every px value inside the declaration sits on the 4px grid.
  const pxs = value.match(/(\d+(?:\.\d+)?)px/g) ?? [];
  return pxs.length > 0 && pxs.every((p) => Number.parseFloat(p) % 4 === 0);
}

describe('the shell rhythm sits on the 4px grid', () => {
  // The named band gaps, exactly as shipped, so a half-step cannot
  // creep back in.
  it('keeps the named rhythm values as grid multiples', () => {
    expect(decl(css, '.hero', 'margin-bottom')).toBe('24px');
    expect(decl(css, '.cmd', 'margin')).toBe('0 0 28px');
    expect(decl(css, '.page-foot', 'margin-top')).toBe('48px');
    expect(decl(css, '.w-foot', 'padding-top')).toBe('12px');
    expect(decl(css, '.w-foot.two-line', 'min-height')).toBe('48px');
  });

  it('lays the hero actions on one row, not a stacked column', () => {
    // The audit found Add plugin and Customize stacked as two rows of
    // buttons; the header actions are one row.
    expect(decl(css, '.hero-actions', 'flex-direction')).toBe('row');
  });

  it('carries no off-grid px step in the named rhythm declarations', () => {
    for (const [selector, property] of [
      ['.hero', 'margin-bottom'],
      ['.cmd', 'margin'],
      ['.page-foot', 'margin-top'],
      ['.w-foot', 'padding-top'],
      ['.hero-meta', 'margin-top'],
      ['.bento', 'gap'],
      ['.w-head', 'gap'],
      ['.widget', 'gap'],
    ] as Array<[string, string]>) {
      const value = decl(css, selector, property);
      expect(value, `${selector} ${property}`).not.toBe('');
      expect(onGrid(value), `${selector} ${property} = ${value} is off the 4px grid`).toBe(true);
    }
  });
});

describe('the two sheets agree on the shared header contract', () => {
  it.each([
    ['the SPA sheet', css],
    ['the server sheet', serverStyles],
  ])('%s styles the icon button at the system size', (_name, sheet) => {
    expect(decl(sheet, '.icon-btn', 'width')).toBe('28px');
    expect(decl(sheet, '.icon-btn', 'height')).toBe('28px');
  });

  it.each([
    ['the SPA sheet', css],
    ['the server sheet', serverStyles],
  ])('%s sets the card title in the 16px/700 title voice', (_name, sheet) => {
    const weight = decl(sheet, '.w-head h2', 'font-weight');
    expect(weight).toBe('700');
    expect(decl(sheet, '.w-head h2', 'font-size')).toBe('16px');
  });

  it.each([
    ['the SPA sheet', css],
    ['the server sheet', serverStyles],
  ])('%s spaces the brand row identically', (_name, sheet) => {
    expect(decl(sheet, '.brand', 'padding')).toBe('2px 8px 18px');
  });

  it.each([
    ['the SPA sheet', css],
    ['the server sheet', serverStyles],
  ])('%s spaces the stamp beside its 7px dot identically', (_name, sheet) => {
    expect(decl(sheet, '.stamp', 'gap')).toBe('7px');
  });

  it.each([
    ['the SPA sheet', css],
    ['the server sheet', serverStyles],
  ])('%s keeps the header row on the 12px internal gap', (_name, sheet) => {
    expect(decl(sheet, '.w-head', 'gap')).toBe('12px');
  });

  it.each([
    ['the SPA sheet', css],
    ['the server sheet', serverStyles],
  ])('%s spaces the foot divider identically', (_name, sheet) => {
    expect(decl(sheet, '.w-foot', 'padding-top')).toBe('12px');
    expect(decl(sheet, '.page-foot', 'margin-top')).toBe('48px');
  });
});

describe('the committed bundle honors the contract', () => {
  // Vite inlines small assets as data: URLs; the CSP's font-src 'self'
  // would silently block any font that arrives that way.
  it('inlines no font as a data url', () => {
    expect(bundleCss, 'font shipped as a data: url, blocked by font-src \'self\'').not.toContain(
      'data:font',
    );
  });

  // The bundle is the product: a source fix that never reaches the
  // committed build ships nothing. One rhythm value and the shipped
  // behavior marks, so staleness fails here instead of silently.
  it('carries the shipped shell rhythm, not a stale build', () => {
    expect(decl(bundleCss, '.hero', 'margin-bottom')).toBe('24px');
    expect(decl(bundleCss, '.w-foot', 'padding-top')).toBe('12px');
  });

  it('carries the overflow menu and the nowrap helper the cards ship', () => {
    expect(bundleCss).toContain('.w-menu{');
    expect(bundleCss).toContain('.w-menuitem{');
    expect(bundleCss).toContain('.nowrap{white-space:nowrap}');
    // The menu's announced behavior lives in the JS bundle: a stale
    // script would ship the dead dots again.
    expect(bundleJs).toContain('aria-haspopup');
    expect(bundleJs).toContain('w-menu');
  });

  it('carries the collapsible rail the shell ships', () => {
    // A source fix that misses the build ships an always-expanded rail:
    // the collapsed rules and the persisted toggle must be in the bundle.
    expect(bundleCss).toContain('.rail-collapsed');
    expect(bundleCss).toContain('.rail-toggle{');
    expect(bundleJs).toContain('agentdesk.railCollapsed');
    expect(bundleJs).toContain('rail-toggle');
  });
});

describe('pressed controls stay inside color', () => {
  it('darkens primary and send controls on press without moving them', () => {
    expect(css).toContain('.btn-primary:active:not(:disabled){box-shadow:none}');
    expect(css).toContain('.cmd-send:active:not(:disabled){filter:brightness(.92)}');
    expect(css).not.toContain('transition:all');
    expect(css).toContain('transition:background-color var(--dur) ease,border-color var(--dur) ease,color var(--dur) ease');
    expect(css).toContain('touch-action:manipulation');
    expect(css).toContain('@media (prefers-reduced-motion:reduce)');
  });
});

describe('marketplace type stays inside the design language', () => {
  it('keeps page titles on the 28px ceiling at every width', () => {
    expect(marketCss).toContain('font-size: 40px');
    expect(marketCss).not.toContain('font-size: 30px');
    expect(marketCss).not.toContain('font-size: 28px');
  });

  it('uses sentence case for labels', () => {
    expect(css).not.toContain('text-transform:uppercase');
    expect(marketCss).not.toContain('text-transform: uppercase');
    expect(adminCss).not.toContain('text-transform: uppercase');
  });

  it('draws catalog icons as strokes without a filled chip', () => {
    for (const selector of ['.mkt-card-icon', '.mkt-detail-icon', '.mkt-pack-icon']) {
      expect(decl(marketCss, selector, 'background'), selector).toBe('none');
      expect(decl(marketCss, selector, 'color'), selector).toBe('var(--accent-text)');
    }
  });

  it('shows a keyboard ring on the marketplace main and keeps the search well ring', () => {
    expect(marketCss).toContain('.mkt-main:focus-visible { outline: 2px solid var(--focus)');
    expect(marketCss).toContain('.mkt-search-field:focus-within');
    expect(marketCss).toContain('.mkt-search-field input:focus-visible { outline: 2px solid var(--focus)');
  });
});

describe('the toolchain matches the system', () => {
  it('depends on the system fonts and not the drift fonts', () => {
    expect(pkg.dependencies['@fontsource/geist']).toBeTruthy();
    expect(pkg.dependencies['@fontsource/geist-mono']).toBeTruthy();
    expect(pkg.dependencies['@fontsource-variable/plus-jakarta-sans']).toBeUndefined();
    expect(pkg.dependencies['@fontsource-variable/inter']).toBeUndefined();
    expect(pkg.dependencies['@fontsource-variable/space-grotesk']).toBeUndefined();
  });

  it('ships a vitest harness wired to jsdom', () => {
    expect(pkg.scripts.test).toBe('vitest run');
    expect(pkg.devDependencies['vitest']).toBeTruthy();
    expect(pkg.devDependencies['jsdom']).toBeTruthy();
    expect(pkg.devDependencies['@testing-library/react']).toBeTruthy();
    expect(pkg.devDependencies['@testing-library/jest-dom']).toBeTruthy();
  });

  it('carries no unused animation, class-helper or utility libraries', () => {
    expect(pkg.dependencies['motion']).toBeUndefined();
    expect(pkg.dependencies['clsx']).toBeUndefined();
    expect(pkg.devDependencies['tailwindcss']).toBeUndefined();
    expect(pkg.devDependencies['@tailwindcss/vite']).toBeUndefined();
  });

  it('styles the sheet without a utility framework', () => {
    expect(css).not.toContain('tailwindcss');
  });

  it('records the system fonts in the license manifest', () => {
    expect(manifest).toContain('Geist');
    expect(manifest).toContain('Geist Mono');
    expect(manifest).not.toContain('Plus Jakarta Sans');
    expect(manifest).not.toContain('Space Grotesk');
    expect(manifest).not.toContain('Inter Variable');
  });

  it('ships the fonts\u2019 OFL files and not the drift fonts\u2019', () => {
    expect(licenses.some((f) => f.startsWith('OFL-Geist'))).toBe(true);
    expect(licenses.some((f) => f.startsWith('OFL-GeistMono'))).toBe(true);
    expect(licenses.some((f) => f === 'OFL-Inter.txt')).toBe(false);
    expect(licenses.some((f) => f === 'OFL-Space-Grotesk.txt')).toBe(false);
  });
});
