// @vitest-environment node
// The dashboard text-fit contract (spec 026). The probe found text leaving
// its box on the desk, the widget header and the rail; these tests read the
// sheet and pin the rules that make text wrap, break or scroll inside the
// box it belongs to. They render nothing.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, '..', '..');
const css = readFileSync(resolve(frontend, 'src/index.css'), 'utf8');

/** The declarations inside the first rule whose selector is exactly this. */
function block(text: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`${escaped}\\{([^}]*)\\}`).exec(text)?.[1] ?? '';
}

/** The value of one declaration inside a selector's first rule. */
function decl(text: string, selector: string, property: string): string {
  const found = block(text, selector);
  const m = found.match(new RegExp(`${property}\\s*:\\s*([^;]+)`));
  return m ? m[1].trim() : '';
}

describe('R1: prose breaks rather than overflows', () => {
  it('gives the root a break-anywhere rule', () => {
    expect(decl(css, 'body', 'overflow-wrap')).toBe('anywhere');
    // The root keeps hiding sideways overflow; the causes are fixed below.
    expect(decl(css, 'body', 'overflow-x')).toBe('hidden');
  });

  it('opts pre out of break-anywhere and lets it scroll', () => {
    expect(decl(css, 'pre', 'overflow-wrap')).toBe('normal');
    expect(decl(css, 'pre', 'overflow-x')).toBe('auto');
  });
});

describe('the rail never spills its column', () => {
  it('lets a rail entry shrink and ellipsizes its label, never its mark', () => {
    expect(decl(css, '.rail a,.rail .nav-off', 'min-width')).toBe('0');
    expect(decl(css, '.rail .rail-label', 'min-width')).toBe('0');
    expect(decl(css, '.rail .rail-label', 'white-space')).toBe('nowrap');
    expect(decl(css, '.rail .rail-label', 'overflow')).toBe('hidden');
    expect(decl(css, '.rail .rail-label', 'text-overflow')).toBe('ellipsis');
    expect(decl(css, '.rail .count', 'flex')).toBe('none');
  });

  it('wraps the brand instead of letting a long name run over the edge', () => {
    expect(decl(css, '.brand .brand-name', 'white-space')).toBe('normal');
    expect(decl(css, '.brand .brand-name', 'min-width')).toBe('0');
  });

  it('ellipsizes the collapse label and keeps the theme row wrapping', () => {
    expect(decl(css, '.rail-toggle-label', 'min-width')).toBe('0');
    expect(decl(css, '.rail-toggle-label', 'overflow')).toBe('hidden');
    expect(decl(css, '.rail-toggle-label', 'text-overflow')).toBe('ellipsis');
    expect(decl(css, '.rail-toggle', 'max-width')).toBe('100%');
    expect(decl(css, '.rail-theme', 'flex-wrap')).toBe('wrap');
  });

  it('keeps the avatar in its fixed square with a reachable label', () => {
    expect(decl(css, '.rail .user > div', 'min-width')).toBe('0');
    expect(decl(css, '.rail .user .avatar', 'overflow')).toBe('hidden');
    expect(decl(css, '.rail .user .avatar', 'text-overflow')).toBe('ellipsis');
    expect(decl(css, '.rail .user .avatar', 'white-space')).toBe('nowrap');
  });
});

describe('the command bar wraps before it squeezes', () => {
  it('wraps the bar and gives the field a text floor', () => {
    expect(decl(css, '.cmd-inner', 'flex-wrap')).toBe('wrap');
    expect(decl(css, '.cmd-field', 'flex')).toBe('1 1 220px');
    expect(decl(css, '.cmd-hint', 'white-space')).toBe('normal');
    expect(decl(css, '.cmd-hint', 'min-width')).toBe('0');
  });

  it('pins the send control and lets it stay inside the bar', () => {
    expect(decl(css, '.cmd-magnet', 'flex')).toBe('none');
    expect(decl(css, '.cmd-magnet', 'max-width')).toBe('100%');
    expect(decl(css, '.cmd-send', 'max-width')).toBe('100%');
  });
});

describe('the cell header wraps and the tag stays reachable', () => {
  it('wraps the header and gives the tag a floor', () => {
    expect(decl(css, '.cell-head', 'flex-wrap')).toBe('wrap');
    expect(decl(css, '.cell-head .tag', 'flex')).toBe('1 1 120px');
    expect(decl(css, '.cell-head .tag', 'min-width')).toBe('0');
    expect(decl(css, '.cell-head .tag', 'text-overflow')).toBe('ellipsis');
    expect(decl(css, '.cell-meta', 'flex')).toBe('none');
    expect(decl(css, '.sample-tag', 'max-width')).toBe('100%');
  });
});

describe('the widget card header wraps and the menu stays in the card', () => {
  it('wraps the header, floors the title and reserves the menu gutter', () => {
    expect(decl(css, '.w-head', 'flex-wrap')).toBe('wrap');
    expect(decl(css, '.w-head', 'position')).toBe('relative');
    expect(decl(css, '.w-head.has-menu', 'padding-right')).toBe('40px');
    expect(decl(css, '.w-head h2', 'flex')).toBe('1 1 120px');
    expect(decl(css, '.w-head h2', 'min-width')).toBe('0');
  });

  it('lets the stamp and badge drop without leaving the card', () => {
    expect(decl(css, '.stamp', 'flex')).toBe('none');
    expect(decl(css, '.stamp', 'max-width')).toBe('100%');
    expect(decl(css, '.stamp', 'overflow-x')).toBe('auto');
    expect(decl(css, '.badge-pilot', 'flex')).toBe('none');
  });

  it('anchors the overflow menu to the card corner and the viewport', () => {
    expect(decl(css, '.w-menu-wrap', 'position')).toBe('absolute');
    expect(decl(css, '.w-menu-wrap', 'top')).toBe('0');
    expect(decl(css, '.w-menu-wrap', 'right')).toBe('0');
    expect(decl(css, '.w-menu', 'max-width')).toBe('calc(100vw - 32px)');
    expect(decl(css, '.w-menu', 'right')).toBe('0');
  });
});

describe('compared values never break and never clip', () => {
  it('resolves the duplicate KPI value rule to nowrap in a scroll well', () => {
    // The sheet used to declare the value twice: break-anywhere first,
    // nowrap second, so the later rule won by accident. No rule may put
    // the break rule back; the one value rule scrolls instead.
    const rules = Array.from(css.matchAll(/\.kpi \.value\{([^}]*)\}/g)).map((m) => m[1]);
    expect(rules.length).toBeGreaterThan(0);
    expect(rules.every((rule) => !rule.includes('overflow-wrap'))).toBe(true);
    expect(decl(css, '.kpi .value', 'white-space')).toBe('nowrap');
    expect(decl(css, '.kpi .value', 'overflow-x')).toBe('auto');
    expect(decl(css, '.kpi .value', 'max-width')).toBe('100%');
  });

  it('keeps the tracker figure and its unit on one line in a scroll well', () => {
    expect(decl(css, '.figure', 'white-space')).toBe('nowrap');
    expect(decl(css, '.figure', 'flex')).toBe('none');
    expect(decl(css, '.figure-unit', 'white-space')).toBe('nowrap');
    expect(decl(css, '.figure-unit', 'flex')).toBe('none');
    expect(decl(css, '.tracker-figure', 'overflow-x')).toBe('auto');
    expect(decl(css, '.tracker-figure', 'max-width')).toBe('100%');
  });

  it('keeps the hero stats on one line', () => {
    expect(decl(css, '.hero-stats dd', 'white-space')).toBe('nowrap');
  });
});

describe('rows that put text beside controls wrap', () => {
  it('keeps button labels whole and inside their box', () => {
    expect(decl(css, '.btn', 'white-space')).toBe('nowrap');
    expect(decl(css, '.btn', 'max-width')).toBe('100%');
    expect(decl(css, '.btn', 'overflow-x')).toBe('auto');
  });

  it('lets the decision actions drop and stay within the card', () => {
    expect(decl(css, '.decision-actions', 'max-width')).toBe('100%');
  });

  it('wraps the tracker title before squeezing it', () => {
    expect(decl(css, '.tracker-title', 'flex-wrap')).toBe('wrap');
    expect(decl(css, '.tracker-title h3', 'flex')).toBe('1 1 120px');
    expect(decl(css, '.tracker-title h3', 'min-width')).toBe('0');
  });

  it('wraps the delta row and keeps the chip on one line', () => {
    expect(decl(css, '.tracker-delta', 'flex-wrap')).toBe('wrap');
    expect(decl(css, '.delta-chip', 'white-space')).toBe('nowrap');
    expect(decl(css, '.delta-chip', 'flex')).toBe('none');
    expect(decl(css, '.delta-chip', 'max-width')).toBe('100%');
  });
});

describe('fixed tracks scroll inside themselves', () => {
  it('scrolls the digest block and its time and source stamps', () => {
    expect(decl(css, '.digest', 'overflow-x')).toBe('auto');
    expect(decl(css, '.digest', 'max-width')).toBe('100%');
    expect(decl(css, '.digest-time', 'white-space')).toBe('nowrap');
    expect(decl(css, '.digest-time', 'overflow-x')).toBe('auto');
    expect(decl(css, '.digest-src', 'white-space')).toBe('nowrap');
    expect(decl(css, '.digest-src', 'overflow-x')).toBe('auto');
    expect(decl(css, '.digest-src', 'max-width')).toBe('100%');
  });

  it('scrolls the dotted moves table inside its own wrapper', () => {
    expect(decl(css, '.moves-wire', 'overflow-x')).toBe('auto');
    expect(decl(css, '.moves-wire', 'max-width')).toBe('100%');
    expect(decl(css, '.mw-head span', 'white-space')).toBe('nowrap');
    expect(decl(css, '.mw-head span', 'overflow-x')).toBe('auto');
  });

  it('scrolls the setup meter and the step mark instead of spilling', () => {
    expect(decl(css, '.setup-meter', 'overflow-x')).toBe('auto');
    expect(decl(css, '.setup-meter-label', 'white-space')).toBe('nowrap');
    expect(decl(css, '.setup-meter-label', 'overflow-x')).toBe('auto');
    expect(decl(css, '.gs-mark', 'white-space')).toBe('nowrap');
    expect(decl(css, '.gs-mark', 'overflow-x')).toBe('auto');
    expect(decl(css, '.gs-title', 'flex')).toBe('1 1 120px');
    expect(decl(css, '.gs-action', 'flex')).toBe('none');
    expect(decl(css, '.gs-action', 'max-width')).toBe('100%');
  });

  it('ellipsizes the stage axis in its fixed tracks', () => {
    expect(decl(css, '.stage-axis span', 'min-width')).toBe('0');
    expect(decl(css, '.stage-axis span', 'white-space')).toBe('nowrap');
    expect(decl(css, '.stage-axis span', 'text-overflow')).toBe('ellipsis');
    expect(decl(css, '.stage-axis small', 'max-width')).toBe('100%');
    expect(decl(css, '.stage-axis small', 'text-overflow')).toBe('ellipsis');
  });
});

describe('the desk health matrix fits its card', () => {
  it('uses the fixed layout with every column visible', () => {
    expect(decl(css, '.matrix', 'table-layout')).toBe('fixed');
    expect(decl(css, '.matrix', 'width')).toBe('100%');
    for (const [index, width] of [[1, '30%'], [2, '28%'], [3, '20%'], [4, '22%']] as Array<[number, string]>) {
      expect(decl(css, `.matrix thead th:nth-child(${index})`, 'width')).toBe(width);
    }
  });

  it('wraps the words and keeps the compared numbers on one line', () => {
    expect(decl(css, '.matrix th,.matrix td', 'white-space')).toBe('normal');
    expect(decl(css, '.matrix th,.matrix td', 'overflow-wrap')).toBe('normal');
    expect(decl(css, '.matrix th,.matrix td', 'overflow-x')).toBe('auto');
    expect(decl(css, '.matrix td.num', 'white-space')).toBe('nowrap');
  });

  it('gives the health cell the whole row so the table has room', () => {
    expect(css).toContain('.brief .cell-health{grid-column:1/-1}');
  });
});

describe('the dashboard gives the lower cards room', () => {
  it('keeps the lower plugin cells two across under the health row', () => {
    // The original span-4 rule still exists; the later rule widens the
    // plugin cells so a pair fills the row.
    const rules = Array.from(css.matchAll(/\.brief \.span-4\{([^}]*)\}/g)).map((m) => m[1]);
    expect(rules).toContain('grid-column:span 6');
  });

  it('keeps the moves scroller inside its cell', () => {
    expect(decl(css, '.table-scroll', 'margin')).toBe('0');
    expect(decl(css, '.table-scroll', 'padding')).toBe('0');
    expect(decl(css, '.table-scroll', 'overflow-x')).toBe('auto');
  });
});
