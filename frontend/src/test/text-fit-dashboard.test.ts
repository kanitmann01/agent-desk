// @vitest-environment node
// The dashboard text-fit contract (spec 026). The probe found text leaving
// its box on the desk, the widget header and the rail; these tests read the
// sheet and pin the rules that make text wrap, break or scroll inside the
// box it belongs to. They render nothing.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { formatGrouped } from '../dashboard/briefModel';
import { kindTag, pluginKind } from '../dashboard/pluginKind';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, '..', '..');
const css = readFileSync(resolve(frontend, 'src/index.css'), 'utf8');

/** The declarations inside the first rule whose selector is exactly this. */
function block(text: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`${escaped}\\{([^}]*)\\}`).exec(text)?.[1] ?? '';
}

/** The declarations inside the last rule whose selector is exactly this. */
function lastBlock(text: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`${escaped}\\{([^}]*)\\}`, 'g');
  let match: RegExpExecArray | null;
  let found = '';
  while ((match = re.exec(text)) !== null) found = match[1];
  return found;
}

/** The value of one declaration inside a selector's first rule. */
function decl(text: string, selector: string, property: string): string {
  const found = block(text, selector);
  const m = found.match(new RegExp(`${property}\\s*:\\s*([^;]+)`));
  return m ? m[1].trim() : '';
}

/** The value of one declaration inside a selector's last rule. */
function lastDecl(text: string, selector: string, property: string): string {
  const found = lastBlock(text, selector);
  const m = found.match(new RegExp(`${property}\\s*:\\s*([^;]+)`));
  return m ? m[1].trim() : '';
}

/** Every balanced block of one media query, in source order. */
function mediaBlocks(text: string, query: string): string[] {
  const marker = `@media (${query}){`;
  const out: string[] = [];
  let start = 0;
  while ((start = text.indexOf(marker, start)) !== -1) {
    let depth = 0;
    for (let i = start + marker.length - 1; i < text.length; i += 1) {
      if (text[i] === '{') depth += 1;
      else if (text[i] === '}') {
        depth -= 1;
        if (depth === 0) {
          out.push(text.slice(start, i + 1));
          start = i + 1;
          break;
        }
      }
    }
  }
  return out;
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

describe('the headline figure prints in full and the layout makes room', () => {
  it('declares the KPI once, on one line, with no scroll well', () => {
    // The sheet used to declare .kpi twice and the value twice. One block
    // remains, with the padding that won, and the value is never cut off
    // and never scrolls.
    expect(css.match(/^\.kpi\{/gm) ?? []).toHaveLength(1);
    expect(lastDecl(css, '.kpi', 'padding')).toBe('4px 0 0');
    const rules = Array.from(css.matchAll(/\.kpi \.value\{([^}]*)\}/g)).map((m) => m[1]);
    expect(rules.length).toBeGreaterThan(0);
    expect(rules.every((rule) => !rule.includes('overflow-wrap'))).toBe(true);
    expect(decl(css, '.kpi .value', 'white-space')).toBe('nowrap');
    // An absent declaration only means something when the rule exists:
    // assert the block first, or a deleted rule would pass this test.
    expect(block(css, '.kpi .value')).not.toBe('');
    expect(decl(css, '.kpi .value', 'overflow-x')).toBe('');
    expect(decl(css, '.kpi .value', 'max-width')).toBe('');
  });

  it('wraps the chart under the figure instead of squeezing either', () => {
    expect(decl(css, '.hero-grid', 'display')).toBe('flex');
    expect(decl(css, '.hero-grid', 'flex-wrap')).toBe('wrap');
    expect(decl(css, '.hero-figure', 'flex')).toBe('0 0 auto');
    expect(decl(css, '.hero-figure', 'min-width')).toBe('0');
    expect(decl(css, '.hero-figure', 'max-width')).toBe('100%');
    expect(decl(css, '.stage-chart', 'flex')).toBe('1 1 280px');
    expect(decl(css, '.stage-chart', 'min-width')).toBe('0');
  });

  it('lets the hero stats wrap when their counts are wide', () => {
    expect(decl(css, '.hero-stats', 'flex-wrap')).toBe('wrap');
    // A stat takes its content width so a nine-character count cannot be
    // squeezed under the next one; the row wraps instead.
    expect(decl(css, '.hero-stats div', 'flex')).toBe('0 0 auto');
    expect(decl(css, '.hero-stats div', 'min-width')).toBe('0');
    expect(decl(css, '.hero-stats dd', 'white-space')).toBe('nowrap');
  });

  it('keeps the tracker figure and its unit on one line with no scroll well', () => {
    expect(decl(css, '.figure', 'white-space')).toBe('nowrap');
    expect(decl(css, '.figure', 'flex')).toBe('none');
    expect(decl(css, '.figure-unit', 'white-space')).toBe('nowrap');
    expect(decl(css, '.figure-unit', 'flex')).toBe('none');
    expect(block(css, '.tracker-figure')).not.toBe('');
    expect(decl(css, '.tracker-figure', 'overflow-x')).toBe('');
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

describe('auto-layout tables break long words without crushing columns', () => {
  it('uses break-word in the sales rows table', () => {
    expect(decl(css, 'table.rows td', 'overflow-wrap')).toBe('break-word');
  });

  it('uses break-word and a scroll wrapper for the plugin table', () => {
    expect(decl(css, '.w-table td', 'overflow-wrap')).toBe('break-word');
    expect(decl(css, '.w-table-block', 'overflow-x')).toBe('auto');
    expect(decl(css, '.w-table-block', 'max-width')).toBe('100%');
  });
});

describe('the plugin timeline keeps time in its own column', () => {
  it('sizes the time column to its content and puts the title in the wide column', () => {
    expect(decl(css, '.w-timeline li', 'grid-template-columns')).toBe('max-content minmax(0,1fr)');
    expect(decl(css, '.w-timeline .w-list-meta', 'grid-column')).toBe('1');
    expect(decl(css, '.w-timeline .w-list-meta', 'grid-row')).toBe('1');
    expect(decl(css, '.w-timeline .w-list-meta', 'white-space')).toBe('nowrap');
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
    // The name is its own block so the ellipsis trims the end of the word,
    // not the middle of a centred flex line.
    expect(decl(css, '.stage-axis .stage-name', 'display')).toBe('block');
    expect(decl(css, '.stage-axis .stage-name', 'max-width')).toBe('100%');
    expect(decl(css, '.stage-axis .stage-name', 'text-overflow')).toBe('ellipsis');
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

  it('breaks a long status word and keeps the numbers readable below 560', () => {
    expect(decl(css, '.matrix td:nth-child(2)', 'overflow-wrap')).toBe('break-word');
    expect(decl(css, '.matrix td.num', 'overflow-x')).toBe('auto');
    const narrow = mediaBlocks(css, 'max-width:560px')
      .find((block) => block.includes('.matrix')) ?? '';
    expect(narrow, 'no 560px matrix media block').not.toBe('');
    expect(narrow).toContain('.matrix thead th:nth-child(1){width:26%}');
    expect(narrow).toContain('.matrix thead th:nth-child(2){width:28%}');
    expect(narrow).toContain('.matrix thead th:nth-child(3){width:22%}');
    expect(narrow).toContain('.matrix thead th:nth-child(4){width:24%}');
  });

  it('keeps the numeric gutter on the 4px grid', () => {
    expect(decl(css, '.matrix .num', 'padding-left')).toBe('12px');
  });

  it('gives the health cell the whole row so the table has room', () => {
    expect(css).toContain('.brief .cell-health{grid-column:1/-1}');
  });

  it('labels the plugin rows as their own group with their own count', () => {
    expect(decl(css, '.matrix-group-line', 'display')).toBe('flex');
    expect(decl(css, '.matrix-group-line', 'flex-wrap')).toBe('wrap');
    expect(decl(css, '.matrix-group-line', 'justify-content')).toBe('space-between');
    expect(decl(css, '.matrix-group-count', 'font-family')).toBe('var(--font-mono)');
  });
});

describe('the tracker reading is one separated block', () => {
  it('draws a top rule and a short heading above the disclosure', () => {
    expect(decl(css, '.tracker-reading', 'display')).toBe('flex');
    expect(decl(css, '.tracker-reading', 'border-top')).toBe('1px solid var(--rule)');
    expect(decl(css, '.tracker-reading', 'padding-top')).toBe('12px');
    expect(decl(css, '.tracker-reading-more summary', 'cursor')).toBe('pointer');
    expect(decl(css, '.tracker-reading-more[open] summary', 'margin-bottom')).toBe('8px');
  });

  it('lets a customize tracker tile take the full row with its figure', () => {
    expect(css).toContain('.cust-cell:has(.tracker-card){grid-column:1/-1}');
  });
});

describe('the dashboard gives the lower cards room', () => {
  it('leaves no dead span-4 override in the brief', () => {
    // The lower row's spans are computed now; a late span-4 rule would
    // silently widen or narrow the cards again.
    expect(css).not.toContain('.brief .span-4{');
  });

  it('keeps the span classes the lower row uses', () => {
    expect(decl(css, '.brief .span-6', 'grid-column')).toBe('span 6');
    expect(decl(css, '.brief .span-12', 'grid-column')).toBe('span 12');
  });

  it('keeps the moves scroller inside its cell', () => {
    expect(decl(css, '.table-scroll', 'margin')).toBe('0');
    expect(decl(css, '.table-scroll', 'padding')).toBe('0');
    expect(decl(css, '.table-scroll', 'overflow-x')).toBe('auto');
  });
});

describe('displayed numbers are grouped, the wire stays raw', () => {
  it('groups a raw integer and keeps a sign and decimals', () => {
    expect(formatGrouped('987654321.12')).toBe('987,654,321.12');
    expect(formatGrouped('+18850')).toBe('+18,850');
    expect(formatGrouped('-1234.5')).toBe('-1,234.5');
    expect(formatGrouped('0')).toBe('0');
    expect(formatGrouped('First reading')).toBe('First reading');
    // A server string that already carries separators is left alone.
    expect(formatGrouped('1,234')).toBe('1,234');
  });
});

describe('one tag name per plugin kind', () => {
  it('uses the dedicated cell names for the tracker and the watch', () => {
    expect(pluginKind('excel-report~q4')).toBe('tracker');
    expect(kindTag('tracker')).toBe('TRACKER');
    expect(pluginKind('competitor-watch')).toBe('watch');
    expect(kindTag('watch')).toBe('PAGE WATCH');
  });

  it('never labels an unknown plugin as a digest', () => {
    expect(pluginKind('a-plugin-from-the-future')).toBe('plugin');
    expect(kindTag('plugin')).toBe('PLUGIN');
    expect(kindTag('digest')).toBe('DIGEST');
  });
});
