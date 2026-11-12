// @vitest-environment node
// The design-contract suite: the stylesheet, the shell HTML, the package
// manifest and the license records must speak the warm-paper system from
// DESIGN.md (docs/design-language.md), and must not carry any of the
// recorded dark-glass drift. These tests read files; they render nothing.
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, '..', '..');
const repo = resolve(frontend, '..');

const css = readFileSync(resolve(frontend, 'src/index.css'), 'utf8');
const html = readFileSync(resolve(frontend, 'index.html'), 'utf8');
const pkg = JSON.parse(readFileSync(resolve(frontend, 'package.json'), 'utf8')) as {
  dependencies: Record<string, string>;
  devDependencies: Record<string, string>;
  scripts: Record<string, string>;
};
const manifest = readFileSync(resolve(repo, 'THIRD-PARTY-LICENSES.md'), 'utf8');
const licenses = readdirSync(resolve(frontend, 'public', 'licenses'));

// The fourteen DESIGN.md frontmatter colors, each asserted as the exact
// hex so a near-miss (a re-darkened green, a colder paper) fails.
const SYSTEM_COLORS: Array<[string, string]> = [
  ['warm ledger paper', '#F6F4EF'],
  ['card white', '#FFFFFF'],
  ['input well', '#FBFAF7'],
  ['hairline', '#E5E1D6'],
  ['ink primary', '#1F2A27'],
  ['ink secondary', '#4C5A55'],
  ['ink muted', '#77847E'],
  ['ink faint', '#A9B1AC'],
  ['ink bottle green', '#14594E'],
  ['green on', '#F6FBF9'],
  ['green soft', '#E4EEE9'],
  ['terracotta alarm', '#B3402A'],
  ['manila flag', '#FBF3E2'],
  ['manila ink', '#8A5A14'],
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

const CARD_AT_REST =
  '0 0 0 1px rgba(31,42,39,.05), 0 1px 2px -1px rgba(31,42,39,.06), 0 2px 4px 0 rgba(31,42,39,.04)';
const CARD_LIFTED = '0 0 0 1px rgba(31,42,39,.07)';

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

  it('declares color-scheme light', () => {
    expect(css).toContain('color-scheme: light');
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
      'radial-gradient',
      'text-shadow',
      'drop-shadow',
      '@property',
      'blur(',
    ]) {
      expect(css, `banned effect survived: ${banned}`).not.toContain(banned);
    }
  });

  it('sets numerals in IBM Plex Mono tabular and text in Plus Jakarta Sans', () => {
    expect(css).toContain('"IBM Plex Mono"');
    expect(css).toContain('tabular-nums');
    expect(css).toContain('"Plus Jakarta Sans"');
  });

  it('imports only the system fonts, self-hosted', () => {
    expect(css).toContain('@fontsource-variable/plus-jakarta-sans');
    expect(css).toContain('@fontsource/ibm-plex-mono');
    expect(css).not.toContain('@fontsource-variable/inter');
    expect(css).not.toContain('@fontsource-variable/space-grotesk');
  });

  it('uses the concentric radii and the full-round pill', () => {
    expect(css).toContain('--r-card:12px');
    expect(css).toContain('--r-control:8px');
    expect(css).toContain('--r-inner:6px');
    expect(css).toContain('999px');
  });

  it('uses the 224px rail beside a 1200px content column', () => {
    expect(css).toContain('grid-template-columns:224px');
    expect(css).toContain('max-width:1200px');
    expect(css).toContain('28px 36px 60px');
  });

  it('keeps the display and KPI at the 28px ceiling', () => {
    expect(css).not.toContain('clamp(');
    expect(css).toContain('font-size:28px');
  });

  it('still freezes animation under prefers-reduced-motion', () => {
    expect(css).toContain('@media (prefers-reduced-motion:reduce)');
  });
});

describe('the SPA shell declares the light paper world', () => {
  it('declares color-scheme light and the paper theme color', () => {
    expect(html).toContain('content="light"');
    expect(html).toContain('#F6F4EF');
    expect(html).not.toContain('#020617');
    expect(html).not.toContain('content="dark"');
  });
});

describe('the toolchain matches the system', () => {
  it('depends on the system fonts and not the drift fonts', () => {
    expect(pkg.dependencies['@fontsource-variable/plus-jakarta-sans']).toBeTruthy();
    expect(pkg.dependencies['@fontsource/ibm-plex-mono']).toBeTruthy();
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

  it('records the system fonts in the license manifest', () => {
    expect(manifest).toContain('Plus Jakarta Sans');
    expect(manifest).toContain('IBM Plex Mono');
    expect(manifest).not.toContain('Space Grotesk');
    expect(manifest).not.toContain('Inter Variable');
  });

  it('ships the fonts\u2019 OFL files and not the drift fonts\u2019', () => {
    expect(licenses.some((f) => f.startsWith('OFL-PlusJakartaSans'))).toBe(true);
    expect(licenses.some((f) => f.startsWith('OFL-IBMPlexMono'))).toBe(true);
    expect(licenses.some((f) => f === 'OFL-Inter.txt')).toBe(false);
    expect(licenses.some((f) => f === 'OFL-Space-Grotesk.txt')).toBe(false);
  });
});
