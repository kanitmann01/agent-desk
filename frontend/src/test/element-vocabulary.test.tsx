// Every kind in the generated vocabulary must reach the dashboard's element
// renderer and carry its kind attribute. The Python export gate proves the
// constant list matches the host; this proves the SPA draws what the host
// says it will.
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { drawableElements, ElementView } from '../dashboard/PluginCardView';
import { ELEMENT_KINDS } from '../plugins/vocabulary';
import type { PluginElement } from '../types';

const SAMPLES: Record<PluginElement['kind'], PluginElement> = {
  metric: { kind: 'metric', value: '12', label: 'Rows' },
  text: { kind: 'text', text: 'Reading the workbook.' },
  delta: { kind: 'delta', label: 'Change', value: '+3', direction: 'up' },
  progress: { kind: 'progress', label: 'Done', value: 6, target: 10, unit: 'rows' },
  list: { kind: 'list', title: 'Top', rows: [{ primary: 'a', secondary: 'b', meta: 'c' }] },
  table: { kind: 'table', columns: ['Name', 'Rows'], rows: [['a', '1']] },
  sparkline: { kind: 'sparkline', label: 'History', points: [1, 4, 2, 9] },
  status: { kind: 'status', text: 'Watching', tone: 'ok' },
  timeline: {
    kind: 'timeline',
    title: 'When',
    items: [{ time: '09:00', title: 'Sync', meta: 'done' }],
  },
  checklist: {
    kind: 'checklist',
    title: 'Todo',
    items: [{ text: 'Ship', done: false, due: 'today' }],
  },
};

describe('the element vocabulary', () => {
  afterEach(cleanup);

  it('is the ten contract kinds', () => {
    expect(ELEMENT_KINDS).toEqual([
      'metric', 'text', 'delta', 'progress', 'list',
      'table', 'sparkline', 'status', 'timeline', 'checklist',
    ]);
    expect(Object.keys(SAMPLES)).toHaveLength(ELEMENT_KINDS.length);
  });

  for (const kind of ELEMENT_KINDS) {
    it(`draws the ${kind} kind`, () => {
      const { container } = render(<ElementView element={SAMPLES[kind]} />);
      const drawn = container.querySelector(`[data-element-kind="${kind}"]`);
      expect(drawn).not.toBeNull();
      expect(drawn?.innerHTML.length).toBeGreaterThan(0);
    });
  }

  it('draws a sparkline as an inline SVG line', () => {
    const { container } = render(<ElementView element={SAMPLES.sparkline} />);
    expect(container.querySelector('svg')).not.toBeNull();
    expect(container.querySelector('polyline')).not.toBeNull();
  });

  it('drops a kind outside the vocabulary', () => {
    const unknown = { kind: 'hologram' } as unknown as PluginElement;
    expect(drawableElements([unknown])).toEqual([]);
    expect(drawableElements([SAMPLES.metric, unknown])).toEqual([SAMPLES.metric]);
  });
});
