import { describe, expect, it } from 'vitest';
import { dealName, formatSigned, moversFromDelta, netPipeline } from '../dashboard/briefModel';

const atlas = (amount: number) => ['Sample: Atlas renewal — 1', 'AMER', 'Prospect', amount];
const field = (amount: number) => ['Sample: Field services expansion — 2', 'EMEA', 'Qualify', amount];

describe('the morning brief movers', () => {
  it('hides the sample row index and keeps the deal name', () => {
    expect(dealName(['Sample: Atlas renewal — 1', 'AMER', 'Prospect', 15120])).toBe('Sample: Atlas renewal');
  });

  it('pairs an edited deal into one row with the signed delta', () => {
    const movers = moversFromDelta({
      added: [atlas(15120), ['Sample: Harbor rollout — 4', 'AMER', 'Negotiate', 22010, '2026-02-01']],
      removed: [atlas(13370), ['Sample: ERP modules add-on — 4', 'AMER', 'Negotiate', 17480, '2026-02-01']],
    });
    const changed = movers.find((mover) => mover.name.startsWith('Sample: Atlas renewal'));
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

  it('signs the net figure', () => {
    expect(formatSigned(2670)).toBe('+2,670');
    expect(formatSigned(-4940)).toBe('−4,940');
    expect(formatSigned(0)).toBe('0');
  });
});
