// @vitest-environment node
// The text-fit contract for the marketplace (spec 026). These tests read
// the two marketplace style sheets and pin the declarations that make a
// publisher's long name, a digest, a validator message or a table cell
// stay inside its own box. They render nothing.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const marketCss = readFileSync(resolve(here, '..', 'marketplace', 'marketplace.css'), 'utf8');
const adminCss = readFileSync(resolve(here, '..', 'marketplace', 'admin-trust.css'), 'utf8');

// The body of one rule, looked up by any selector in its selector list.
// Media-query wrappers are skipped by matching only at rule depth; the
// sheets here keep every selector under test at the top level.
function ruleBody(css: string, selector: string): string {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const re = /([^{}@]+)\{([^{}]*)\}/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(stripped)) !== null) {
    const selectors = match[1].split(',').map((item) => item.trim());
    if (selectors.includes(selector)) return match[2];
  }
  return '';
}

function decl(css: string, selector: string, property: string): string {
  const body = ruleBody(css, selector);
  const match = body.match(new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*([^;]+)`));
  return match ? match[1].trim() : '';
}

describe('R1 prose breaks rather than overflows', () => {
  it('breaks words only when one would overflow on the marketplace roots', () => {
    expect(decl(marketCss, '.mkt-main', 'overflow-wrap'), '.mkt-main').toBe('anywhere');
    expect(decl(marketCss, '.mkt-page', 'overflow-wrap'), '.mkt-page').toBe('anywhere');
    expect(decl(marketCss, '.mkt-sheet', 'overflow-wrap'), '.mkt-sheet').toBe('anywhere');
  });

  it('keeps code, digests and fingerprints whole or scrolling', () => {
    expect(decl(marketCss, '.mkt-page code', 'overflow-wrap'), '.mkt-page code').toBe('normal');
    expect(decl(marketCss, '.mkt-page code', 'white-space'), '.mkt-page code').toBe('nowrap');
    expect(decl(marketCss, '.mkt-page code', 'max-width'), '.mkt-page code').toBe('100%');
    expect(decl(marketCss, '.mkt-page code', 'overflow-x'), '.mkt-page code').toBe('auto');
    expect(decl(marketCss, '.mkt-page code', 'display'), '.mkt-page code').toBe('inline-block');

    expect(decl(marketCss, '.mkt-digest code', 'overflow-wrap'), '.mkt-digest code').toBe('normal');
    expect(decl(marketCss, '.mkt-digest code', 'white-space'), '.mkt-digest code').toBe('nowrap');

    expect(decl(marketCss, '.mkt-facts strong', 'overflow-wrap'), '.mkt-facts strong').toBe('normal');
    expect(decl(marketCss, '.mkt-facts strong', 'white-space'), '.mkt-facts strong').toBe('nowrap');
    expect(decl(marketCss, '.mkt-facts strong', 'overflow-x'), '.mkt-facts strong').toBe('auto');

    expect(decl(marketCss, '.mkt-proof dd', 'overflow-wrap'), '.mkt-proof dd').toBe('normal');
    expect(decl(marketCss, '.mkt-proof dd', 'overflow-x'), '.mkt-proof dd').toBe('auto');

    expect(decl(adminCss, '.mkt-page .mkt-fingerprint', 'overflow-wrap'), '.mkt-page .mkt-fingerprint').toBe('normal');
    expect(decl(adminCss, '.mkt-page .mkt-fingerprint', 'white-space'), '.mkt-page .mkt-fingerprint').toBe('nowrap');
    expect(decl(adminCss, '.mkt-page .mkt-fingerprint', 'overflow-x'), '.mkt-page .mkt-fingerprint').toBe('auto');
  });
});

describe('R2 a text-holding item can shrink', () => {
  it('lets panels, table wrappers and fact cells shrink inside their tracks', () => {
    expect(decl(marketCss, '.mkt-panel', 'min-width'), '.mkt-panel').toBe('0');
    expect(decl(marketCss, '.mkt-table-wrap', 'min-width'), '.mkt-table-wrap').toBe('0');
    expect(decl(marketCss, '.mkt-detail-cols > *', 'min-width'), '.mkt-detail-cols > *').toBe('0');
    expect(decl(marketCss, '.mkt-facts > div', 'min-width'), '.mkt-facts > div').toBe('0');
    expect(decl(marketCss, '.mkt-facts span', 'min-width'), '.mkt-facts span').toBe('0');
    expect(decl(marketCss, '.mkt-facts strong', 'min-width'), '.mkt-facts strong').toBe('0');
    expect(decl(marketCss, '.mkt-digest', 'min-width'), '.mkt-digest').toBe('0');
  });

  it('lets the sample card list cells shrink inside their tracks', () => {
    expect(decl(marketCss, '.mkt-sample-grid .w-element', 'min-width'), '.mkt-sample-grid .w-element').toBe('0');
    expect(decl(marketCss, '.mkt-sample-grid .w-list-primary', 'min-width'), '.mkt-sample-grid .w-list-primary').toBe('0');
    expect(decl(marketCss, '.mkt-sample-grid .w-list-secondary', 'min-width'), '.mkt-sample-grid .w-list-secondary').toBe('0');
    expect(decl(marketCss, '.mkt-sample-grid .w-list-meta', 'min-width'), '.mkt-sample-grid .w-list-meta').toBe('0');
  });
});

describe('R3 a text row wraps before it squeezes', () => {
  it('wraps the card identity row before squeezing the title', () => {
    expect(decl(marketCss, '.mkt-card-top', 'flex-wrap'), '.mkt-card-top').toBe('wrap');
    expect(decl(marketCss, '.mkt-card-id', 'flex'), '.mkt-card-id').toBe('1 1 120px');
    expect(decl(marketCss, '.mkt-version', 'flex'), '.mkt-version').toBe('none');
  });

  it('lets an oversized control scroll its whole label instead of breaking it', () => {
    expect(decl(marketCss, '.mkt-page .btn', 'flex'), '.mkt-page .btn').toBe('0 1 auto');
    expect(decl(marketCss, '.mkt-page .btn', 'min-width'), '.mkt-page .btn').toBe('0');
    expect(decl(marketCss, '.mkt-page .btn', 'max-width'), '.mkt-page .btn').toBe('100%');
    expect(decl(marketCss, '.mkt-page .btn', 'overflow-x'), '.mkt-page .btn').toBe('auto');
  });
});

describe('R4 a chip stays inside its card', () => {
  it('caps chips, tags and status words at the card width', () => {
    expect(decl(marketCss, '.mkt-chip', 'max-width'), '.mkt-chip').toBe('100%');
    expect(decl(marketCss, '.mkt-chip', 'overflow'), '.mkt-chip').toBe('hidden');
    expect(decl(marketCss, '.mkt-chip', 'text-overflow'), '.mkt-chip').toBe('ellipsis');
    expect(decl(marketCss, '.mkt-tag', 'max-width'), '.mkt-tag').toBe('100%');
    expect(decl(marketCss, '.mkt-tag', 'white-space'), '.mkt-tag').toBe('nowrap');
    expect(decl(marketCss, '.mkt-tag', 'overflow-x'), '.mkt-tag').toBe('auto');
    expect(decl(marketCss, '.mkt-status', 'max-width'), '.mkt-status').toBe('100%');
  });
});

describe('R3 the featured row keeps its figure and category whole', () => {
  it('wraps the pace row and scrolls the category line instead of breaking it', () => {
    expect(decl(marketCss, '.mini-pace-row', 'flex-wrap'), '.mini-pace-row').toBe('wrap');
    expect(decl(marketCss, '.mkt-row-featured .mini-pace-fig', 'flex'),
      '.mkt-row-featured .mini-pace-fig').toBe('none');
    expect(decl(marketCss, '.mkt-row-featured .mini-pace-fig', 'white-space'),
      '.mkt-row-featured .mini-pace-fig').toBe('nowrap');
    expect(decl(marketCss, '.mkt-row-featured .mkt-row-cat', 'overflow-wrap'),
      '.mkt-row-featured .mkt-row-cat').toBe('normal');
    expect(decl(marketCss, '.mkt-row-featured .mkt-row-cat', 'white-space'),
      '.mkt-row-featured .mkt-row-cat').toBe('nowrap');
    expect(decl(marketCss, '.mkt-row-featured .mkt-row-cat', 'overflow-x'),
      '.mkt-row-featured .mkt-row-cat').toBe('auto');
  });
});

describe('R6 the admin policy diff scrolls in its wrapper', () => {
  it('keeps policy values whole inside the table that scrolls', () => {
    expect(decl(adminCss, '.mkt-diff code', 'white-space'), '.mkt-diff code').toBe('nowrap');
    expect(decl(adminCss, '.mkt-diff code', 'overflow-wrap'), '.mkt-diff code').toBe('normal');
  });
});

describe('R6 a table scrolls inside its own wrapper', () => {
  it('scrolls the wrapper and keeps every cell whole', () => {
    expect(decl(marketCss, '.mkt-table-wrap', 'overflow-x'), '.mkt-table-wrap').toBe('auto');
    expect(decl(marketCss, '.mkt-table-wrap th', 'white-space'), '.mkt-table-wrap th').toBe('nowrap');
    expect(decl(marketCss, '.mkt-table-wrap td', 'white-space'), '.mkt-table-wrap td').toBe('nowrap');
  });
});

describe('R3-R6 the dashboard sample inside a marketplace page', () => {
  it('gives the sample list a text track and a bounded value track', () => {
    expect(decl(marketCss, '.mkt-sample-grid .w-list li', 'grid-template-columns'),
      '.mkt-sample-grid .w-list li').toBe('minmax(120px, 1fr) minmax(0, 40%)');
    expect(decl(marketCss, '.mkt-sample-grid .w-list-meta', 'max-width'),
      '.mkt-sample-grid .w-list-meta').toBe('100%');
    expect(decl(marketCss, '.mkt-sample-grid .w-list-meta', 'overflow-x'),
      '.mkt-sample-grid .w-list-meta').toBe('auto');
  });
});
