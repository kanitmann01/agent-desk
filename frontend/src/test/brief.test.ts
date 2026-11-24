import { describe, expect, it } from 'vitest';
import { agentCheckedLine, decisionsEmptyText, dealName, deskCheckAlert, formatSigned, moversFromDelta, netByStage, netPipeline, recommendationRows } from '../dashboard/briefModel';

const atlas = (amount: number) => ['Halvorsen Freight renewal', 'AMER', 'Prospect', amount];
const field = (amount: number) => ['Kestrel Foods pilot', 'EMEA', 'Qualify', amount];

describe('the morning brief movers', () => {
  it('hides the sample row index and keeps the deal name', () => {
    expect(dealName(['Halvorsen Freight renewal - 1', 'AMER', 'Prospect', 15120])).toBe('Halvorsen Freight renewal');
    // The em dash spelling some exports use still strips, via the escape.
    expect(dealName(['Halvorsen Freight renewal \u2014 1', 'AMER', 'Prospect', 15120])).toBe('Halvorsen Freight renewal');
  });

  it('pairs an edited deal into one row with the signed delta', () => {
    const movers = moversFromDelta({
      added: [atlas(15120), ['Marlow & Finch support retainer', 'AMER', 'Negotiate', 22010, '2026-02-01']],
      removed: [atlas(13370), ['Sato Instruments pilot', 'AMER', 'Negotiate', 17480, '2026-02-01']],
    });
    const changed = movers.find((mover) => mover.name.startsWith('Halvorsen Freight renewal'));
    expect(changed).toMatchObject({
      kind: 'changed',
      previousName: null,
      meta: 'AMER · Prospect',
      oldAmount: 13370,
      newAmount: 15120,
      delta: 1750,
    });
    expect(movers.find((mover) => mover.previousName)).toBeUndefined();
    expect(movers.filter((mover) => mover.kind !== 'changed').map((mover) => mover.kind).sort()).toEqual(['added', 'removed']);
  });

  it('keeps a deal that only arrived or only left', () => {
    const movers = moversFromDelta({
      added: [field(9800)],
      removed: [atlas(13370)],
    });
    expect(movers.map((mover) => mover.kind).sort()).toEqual(['added', 'removed']);
    expect(netPipeline({ added: [field(9800)], removed: [atlas(13370)] })).toBe(9800 - 13370);
  });

  it('nets the moves per stage for the hero chart', () => {
    const movers = moversFromDelta({
      added: [atlas(15120), field(9800)],
      removed: [atlas(13370)],
    });
    const stages = netByStage(movers);
    expect(stages).toEqual([
      { stage: 'Qualify', net: 9800, deals: 1 },
      { stage: 'Prospect', net: 1750, deals: 1 },
    ]);
  });

  it('signs the net figure', () => {
    expect(formatSigned(2670)).toBe('+2,670');
    expect(formatSigned(-4940)).toBe('−4,940');
    expect(formatSigned(0)).toBe('0');
  });
});

describe('the morning brief desk check', () => {
  const finding = {
    id: 'inbox-unreadable-rows',
    title: '1 inbox card this version cannot read',
    cause: 'This version has no card kind called commitment, so the row stays in the inbox database, hidden from the list.',
    severity: 'attention' as const,
    confident: true,
    fix: 'auto' as const,
    fixLabel: 'Fix it',
    href: '',
    detail: { count: 1, kinds: ['commitment'] },
  };

  it('shows desk-check alert when attention > 0', () => {
    expect(deskCheckAlert({ attention: 1, top: finding })).toEqual({
      label: 'Desk check: 1 inbox card this version cannot read · Open',
      href: '/settings#desk-check',
    });
  });

  it('stays quiet when nothing wants attention', () => {
    expect(deskCheckAlert({ attention: 0, top: null })).toBeNull();
    expect(deskCheckAlert(undefined)).toBeNull();
  });
});

describe('the morning brief agent loop line', () => {
  it('shows the clock time of the last pass', () => {
    expect(agentCheckedLine({ lastRunTs: 1732160400, nextRunTs: 1732164000, enabled: true }))
      .toMatch(/^Agent checked at \d{1,2}:\d{2}$/);
  });

  it('stays quiet before the first pass', () => {
    expect(agentCheckedLine(undefined)).toBeNull();
    expect(agentCheckedLine({ lastRunTs: null, nextRunTs: null, enabled: true })).toBeNull();
  });

  it('drops the line when the interval is Off', () => {
    // Ticket #194's browser check: with checks off the line goes away
    // and the empty states say "Automatic checks are off."
    expect(agentCheckedLine({ lastRunTs: 1732160400, nextRunTs: null, enabled: false })).toBeNull();
  });
});

describe('the morning brief decisions', () => {
  const data = (recommendations?: unknown[], agentLoop?: unknown) => ({
    recommendations,
    agentLoop,
  }) as never;

  const halvorsen = {
    cardId: 'card-1',
    title: 'Halvorsen Freight: December 15 (in 24 days)',
    why: 'You told the desk this deadline; it is 24 days away.',
    whySource: 'rule' as const,
    score: null,
    due: '2026-12-15',
    href: '/agents',
    actionLabel: 'Open Agents',
    sample: true,
    cites: [3],
  };

  it('renders waiting recommendations before the setup decisions', () => {
    const { rows, more } = recommendationRows(data([halvorsen]));
    expect(rows).toEqual([{
      key: 'card-1',
      cardId: 'card-1',
      title: 'Halvorsen Freight: December 15 (in 24 days)',
      why: 'You told the desk this deadline; it is 24 days away.',
      href: '/agents',
      actionLabel: 'Open Agents',
      sample: true,
    }]);
    expect(more).toBe(0);
  });

  it('shows three recommendation rows and counts the rest', () => {
    const many = Array.from({ length: 5 }, (_, i) => ({ ...halvorsen, cardId: 'card-' + i }));
    const { rows, more } = recommendationRows(data(many));
    expect(rows).toHaveLength(3);
    expect(more).toBe(2);
  });

  it('marks a model-ranked why line', () => {
    const [row] = recommendationRows(data([{ ...halvorsen, whySource: 'model' }])).rows;
    expect(row.why).toBe('You told the desk this deadline; it is 24 days away. · ranked by your endpoint');
  });

  it('treats an engine-sourced why line as the rule text', () => {
    const [row] = recommendationRows(data([{ ...halvorsen, whySource: 'engine' }])).rows;
    expect(row.why).toBe('You told the desk this deadline; it is 24 days away.');
  });

  it('falls back to the setup decisions when there are no recommendations', () => {
    expect(recommendationRows(data()).rows).toEqual([]);
    expect(decisionsEmptyText(undefined)).toBe('Nothing needs a decision.');
  });

  it('says when the desk checks again, or that automatic checks are off', () => {
    expect(decisionsEmptyText({ lastRunTs: 0, nextRunTs: 0, enabled: false })).toBe('Automatic checks are off.');
    expect(decisionsEmptyText({ lastRunTs: 0, nextRunTs: null, enabled: true })).toBe('Nothing needs a decision.');
    expect(decisionsEmptyText({ lastRunTs: 0, nextRunTs: 4102444800, enabled: true })).toContain('Nothing needs a decision. The desk checks again at ');
  });
});
