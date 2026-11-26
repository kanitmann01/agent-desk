import { createElement, type ReactNode } from 'react';
import { act, cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AgentFace from '../face/AgentFace';
import { createFaceBrain, prefersReducedMotion, type FaceClock } from '../face/brain';
import {
  ACTIVE_FACE_CONFIG,
  DEFAULT_FACE_PRESET,
  FACE_PRESET_IDS,
  FACE_PRESETS,
  resolveFaceConfig,
} from '../face/config';
import { FaceProvider, useFaceActions, useFaceContext } from '../face/FaceProvider';
import FaceSlot from '../face/FaceSlot';
import {
  comparePriority,
  DONE_DURATION_MS,
  FACE_MOODS,
  FACE_PRIORITY_ORDER,
  formatFaceTooltip,
  MOOD_POSES,
  resolveActivityPriority,
  type FaceMood,
} from '../face/moods';
import { AGENT_NAME } from '../face/name';
import { useFaceActivity, type UseFaceActivityOptions } from '../face/useFaceActivity';

interface FakeScheduler {
  clock: FaceClock;
  nowMs: () => number;
  advanceTime: (ms: number) => void;
  flushFrames: (maxFrames?: number) => number;
  pendingFrameCount: () => number;
  pendingTimerCount: () => number;
}

function createFakeScheduler(randomValue = 0.5): FakeScheduler {
  let now = 0;
  let nextId = 1;
  const frames = new Map<number, (nowMs: number) => void>();
  const timers = new Map<number, { at: number; cb: () => void }>();

  const clock: FaceClock = {
    now: () => now,
    requestFrame: (cb) => {
      const id = nextId++;
      frames.set(id, cb);
      return id;
    },
    cancelFrame: (id) => {
      frames.delete(id);
    },
    setTimer: (cb, ms) => {
      const id = nextId++;
      timers.set(id, { at: now + ms, cb });
      return id;
    },
    clearTimer: (id) => {
      timers.delete(id);
    },
    random: () => randomValue,
  };

  function runDueTimers(): void {
    for (;;) {
      let earliestId: number | null = null;
      let earliestAt = Infinity;
      for (const [id, entry] of timers.entries()) {
        if (entry.at <= now && entry.at < earliestAt) {
          earliestAt = entry.at;
          earliestId = id;
        }
      }
      if (earliestId === null) break;
      const entry = timers.get(earliestId)!;
      timers.delete(earliestId);
      entry.cb();
    }
  }

  return {
    clock,
    nowMs: () => now,
    advanceTime: (ms: number) => {
      now += ms;
      runDueTimers();
    },
    flushFrames: (maxFrames = 120) => {
      let ran = 0;
      while (frames.size > 0 && ran < maxFrames) {
        const batch = Array.from(frames.entries());
        frames.clear();
        now += 16;
        runDueTimers();
        for (const [, cb] of batch) {
          cb(now);
          ran += 1;
        }
      }
      return ran;
    },
    pendingFrameCount: () => frames.size,
    pendingTimerCount: () => timers.size,
  };
}

function makeDomElements() {
  const box = document.createElement('span');
  const leftEye = document.createElement('span');
  const rightEye = document.createElement('span');
  box.append(leftEye, rightEye);
  document.body.appendChild(box);
  box.getBoundingClientRect = () => ({
    left: 20,
    top: 20,
    right: 52,
    bottom: 52,
    width: 32,
    height: 32,
    x: 20,
    y: 20,
    toJSON: () => ({}),
  });
  return { box, leftEye, rightEye };
}

function parseEyeTransform(transform: string): { x: number; y: number; sx: number; sy: number } {
  const t = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec(transform);
  const s = /scale\(([-\d.]+),\s*([-\d.]+)\)/.exec(transform);
  return {
    x: t ? Number(t[1]) : 0,
    y: t ? Number(t[2]) : 0,
    sx: s ? Number(s[1]) : 1,
    sy: s ? Number(s[2]) : 1,
  };
}

afterEach(() => {
  cleanup();
  document.body.innerHTML = '';
  vi.restoreAllMocks();
  vi.useRealTimers();
  Object.defineProperty(document, 'visibilityState', {
    value: 'visible',
    configurable: true,
  });
});

describe('name and moods', () => {
  it('defines AGENT_NAME once and formats tooltips cleanly', () => {
    expect(FACE_MOODS).toEqual([
      'idle',
      'listening',
      'thinking',
      'reading',
      'working',
      'waiting',
      'blocked',
      'done',
    ]);
    expect(formatFaceTooltip('idle')).toBe(AGENT_NAME);
    expect(formatFaceTooltip('thinking')).toBe(`${AGENT_NAME}: Thinking`);
    expect(formatFaceTooltip('working', 'Reading your description')).toBe(
      `${AGENT_NAME}: Reading your description`,
    );
  });

  it('orders priorities as request -> done -> blocked -> waiting -> pass -> listening -> idle', () => {
    expect(FACE_PRIORITY_ORDER).toEqual([
      'request',
      'done',
      'blocked',
      'waiting',
      'pass',
      'listening',
      'idle',
    ]);
    expect(resolveActivityPriority('thinking', 'request')).toBe('request');
    expect(resolveActivityPriority('idle', 'request')).toBe('idle');
    expect(resolveActivityPriority('done')).toBe('done');
    expect(resolveActivityPriority('blocked')).toBe('blocked');
    expect(resolveActivityPriority('waiting')).toBe('waiting');
    expect(resolveActivityPriority('working', 'pass')).toBe('pass');
    expect(resolveActivityPriority('listening')).toBe('listening');
    expect(resolveActivityPriority('idle')).toBe('idle');

    for (let i = 0; i < FACE_PRIORITY_ORDER.length - 1; i += 1) {
      expect(comparePriority(FACE_PRIORITY_ORDER[i], FACE_PRIORITY_ORDER[i + 1])).toBeLessThan(0);
    }
  });
});

describe('face brain animation and DOM styles', () => {
  it('eases monotonically with exponential ease-out and zero overshoot', () => {
    const dom = makeDomElements();
    const sched = createFakeScheduler(0.5);
    const brain = createFaceBrain(dom, { clock: sched.clock, reducedMotion: false });
    brain.start();

    brain.setMood('listening');
    const targetX = MOOD_POSES.listening.lookX;
    let prevX = -Infinity;
    for (let i = 0; i < 20; i += 1) {
      brain.step(20);
      const { x } = parseEyeTransform(dom.leftEye.style.transform);
      expect(x).toBeGreaterThanOrEqual(prevX);
      expect(x).toBeLessThanOrEqual(targetX + 0.0001);
      prevX = x;
    }
    expect(prevX).toBeGreaterThan(targetX * 0.9);
    brain.destroy();
  });

  it('renders distinct DOM style poses across all 8 moods and DescribePlugin row steps', () => {
    const dom = makeDomElements();
    const sched = createFakeScheduler(0.5);
    const brain = createFaceBrain(dom, { clock: sched.clock, reducedMotion: false });
    brain.start();

    const transformsByMood = new Map<FaceMood, string>();
    for (const mood of FACE_MOODS) {
      brain.setMood(mood);
      for (let i = 0; i < 30; i += 1) brain.step(30);
      transformsByMood.set(mood, dom.leftEye.style.transform);
    }

    expect(dom.leftEye.dataset.shape).toBe('arc');
    expect(dom.leftEye.style.borderRadius).toBe('99px 99px 4px 4px');

    brain.setMood('blocked');
    for (let i = 0; i < 30; i += 1) brain.step(30);
    expect(dom.leftEye.dataset.shape).toBe('flat');
    expect(dom.leftEye.style.borderRadius).toBe('1px');

    // Reading scans across horizontal lines.
    brain.setMood('reading');
    brain.step(100);
    const readA = parseEyeTransform(dom.leftEye.style.transform).x;
    brain.step(400);
    const readB = parseEyeTransform(dom.leftEye.style.transform).x;
    expect(readB).not.toBe(readA);

    // Working supports optional row-stepping focus for DescribePlugin.
    brain.setMood('working', { stepIndex: 0 });
    for (let i = 0; i < 25; i += 1) brain.step(30);
    const row0Y = parseEyeTransform(dom.leftEye.style.transform).y;
    brain.setMood('working', { stepIndex: 4 });
    for (let i = 0; i < 25; i += 1) brain.step(30);
    const row4Y = parseEyeTransform(dom.leftEye.style.transform).y;
    expect(row4Y).toBeGreaterThan(row0Y);

    // Check that idle, listening, thinking, waiting, blocked, done are distinguishable.
    expect(transformsByMood.get('idle')).not.toBe(transformsByMood.get('listening'));
    expect(transformsByMood.get('thinking')).not.toBe(transformsByMood.get('waiting'));
    expect(transformsByMood.get('blocked')).not.toBe(transformsByMood.get('done'));
    brain.destroy();
  });

  it('runs autonomous blink (3-6 s) and gaze drift (2-4 s) in idle', () => {
    const dom = makeDomElements();
    // random = 0 -> blink at 3000ms, drift at 2000ms, curious look triggered (< 0.25)
    const sched = createFakeScheduler(0);
    const brain = createFaceBrain(dom, { clock: sched.clock, reducedMotion: false });
    brain.start();

    // Advance 2050ms -> drift + curious look fires.
    for (let t = 0; t < 2050; t += 50) brain.step(50);
    const drifted = parseEyeTransform(dom.leftEye.style.transform);
    expect(Math.abs(drifted.x) + Math.abs(drifted.y)).toBeGreaterThan(0.2);

    // Advance to ~3040ms -> blink closes eyes.
    for (let t = 2050; t < 3045; t += 15) brain.step(15);
    const blinking = parseEyeTransform(dom.leftEye.style.transform);
    expect(blinking.sy).toBeLessThan(0.4);

    // Advance past blink open -> eyes return near open scale.
    for (let t = 0; t < 400; t += 20) brain.step(20);
    const opened = parseEyeTransform(dom.leftEye.style.transform);
    expect(opened.sy).toBeGreaterThan(0.8);
    brain.destroy();
  });

  it('tracks pointer proximity, turns toward command bar target, and squashes on click', () => {
    const dom = makeDomElements();
    const sched = createFakeScheduler(0.5);
    const brain = createFaceBrain(dom, { clock: sched.clock, reducedMotion: false });
    brain.start();

    // Pointer to the bottom-right within proximity.
    brain.setPointer(160, 100);
    for (let i = 0; i < 20; i += 1) brain.step(25);
    const pointed = parseEyeTransform(dom.leftEye.style.transform);
    expect(pointed.x).toBeGreaterThan(0.5);
    expect(pointed.y).toBeGreaterThan(0.2);

    // Pointer out of proximity clears back toward rest.
    brain.setPointer(2000, 2000);
    for (let i = 0; i < 30; i += 1) brain.step(30);
    const settled = parseEyeTransform(dom.leftEye.style.transform);
    expect(Math.abs(settled.x)).toBeLessThan(0.1);

    // Command bar target while listening.
    brain.setMood('listening');
    brain.setLookTarget({ x: 300, y: 120 });
    for (let i = 0; i < 20; i += 1) brain.step(25);
    const listeningEye = parseEyeTransform(dom.leftEye.style.transform);
    expect(listeningEye.x).toBeGreaterThan(1);
    expect(listeningEye.sy).toBeGreaterThan(1.1);

    // Click playful squash changes box.style.transform and settles back without changing mood.
    brain.triggerSquash();
    brain.step(30);
    expect(dom.box.style.transform).toContain('scale(');
    for (let i = 0; i < 30; i += 1) brain.step(30);
    expect(brain.getState().mood).toBe('listening');
    brain.destroy();
  });

  it('sleeps with no active rAF loop when settled and stops when tab is hidden', () => {
    const dom = makeDomElements();
    const sched = createFakeScheduler(0.5);
    const brain = createFaceBrain(dom, { clock: sched.clock, reducedMotion: false });
    brain.start();

    // Starts in idle settled: no active rAF loop, only a single wake timer.
    expect(sched.pendingFrameCount()).toBe(0);
    expect(brain.getState().sleeping).toBe(true);

    // Transition to waiting: animates via rAF until settled, then sleeps again.
    brain.setMood('waiting');
    expect(sched.pendingFrameCount()).toBe(1);
    sched.flushFrames(120);
    expect(sched.pendingFrameCount()).toBe(0);
    expect(brain.getState().sleeping).toBe(true);

    // Continuous mood ('working') runs frames while visible, then stops when tab hidden.
    brain.setMood('working');
    expect(sched.pendingFrameCount()).toBe(1);
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(sched.pendingFrameCount()).toBe(0);
    expect(sched.pendingTimerCount()).toBe(0);
    expect(brain.getState().hidden).toBe(true);

    // Returning visible resumes frames.
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(sched.pendingFrameCount()).toBe(1);
    brain.destroy();
  });

  it('keeps click squash and stepIndex pulses working after idle sleep advances clock', () => {
    const dom = makeDomElements();
    const sched = createFakeScheduler(0.5);
    const brain = createFaceBrain(dom, { clock: sched.clock, reducedMotion: false });
    brain.start();

    expect(brain.getState().sleeping).toBe(true);
    sched.advanceTime(1000);

    brain.triggerSquash();
    expect(sched.pendingFrameCount()).toBe(1);
    sched.advanceTime(16);
    sched.flushFrames(2);
    expect(dom.box.style.transform).toContain('scale(');

    sched.flushFrames(120);
    sched.advanceTime(1000);
    brain.setMood('working', { stepIndex: 1 });
    sched.advanceTime(16);
    sched.flushFrames(2);
    expect(dom.box.style.transform).toContain('scale(');
    brain.destroy();
  });

  it('freezes to one still pose per mood under prefers-reduced-motion and handles missing matchMedia', () => {
    const originalMatchMedia = window.matchMedia;
    Object.defineProperty(window, 'matchMedia', { value: undefined, configurable: true });
    expect(prefersReducedMotion()).toBe(false);
    Object.defineProperty(window, 'matchMedia', { value: originalMatchMedia, configurable: true });

    const dom = makeDomElements();
    const sched = createFakeScheduler(0.5);
    const brain = createFaceBrain(dom, { clock: sched.clock, reducedMotion: true });
    brain.start();

    expect(sched.pendingFrameCount()).toBe(0);
    expect(sched.pendingTimerCount()).toBe(0);

    brain.setMood('thinking');
    const poseA = dom.leftEye.style.transform;
    brain.step(500);
    expect(dom.leftEye.style.transform).toBe(poseA);

    const boxPose = dom.box.style.transform;
    brain.triggerSquash();
    expect(dom.box.style.transform).toBe(boxPose);

    brain.setMood('done');
    expect(dom.leftEye.style.borderRadius).toBe('99px 99px 4px 4px');
    expect(sched.pendingFrameCount()).toBe(0);
    brain.destroy();
  });
});

describe('AgentFace, FaceProvider, FaceSlot, and useFaceActivity', () => {
  it('renders AgentFace as decorative, non-focusable, with native title and click squash only', () => {
    const { container } = render(
      createElement(AgentFace, { mood: 'waiting', size: 'sm', label: 'Inbox needs review' }),
    );
    const face = container.querySelector('.face-box') as HTMLElement;
    expect(face).toBeInTheDocument();
    expect(face).toHaveAttribute('aria-hidden', 'true');
    expect(face).toHaveAttribute('title', `${AGENT_NAME}: Inbox needs review`);
    expect(face.classList.contains('face-sm')).toBe(true);
    expect(face.getAttribute('tabindex')).toBeNull();
    expect(
      container.querySelectorAll('button, a, input, [tabindex]:not([tabindex="-1"])'),
    ).toHaveLength(0);

    fireEvent.click(face);
    expect(face).toHaveAttribute('data-mood', 'waiting');
  });

  function ActivityProbe(props: UseFaceActivityOptions) {
    useFaceActivity(props);
    return null;
  }

  function DoneTrigger({ label, scope }: { label?: string; scope?: 'global' | 'modal' }) {
    const ctx = useFaceContext();
    return createElement(
      'button',
      { type: 'button', onClick: () => ctx?.notifyDone(label, scope) },
      'Finish',
    );
  }

  function renderDesk(children: ReactNode) {
    return render(createElement(FaceProvider, { trackPointer: false }, children));
  }

  it('resolves priority order across concurrent activities and cleans up on unmount', () => {
    const { container, rerender } = renderDesk(
      createElement(
        'div',
        null,
        createElement(FaceSlot, { slot: 'rail' }),
        createElement(ActivityProbe, { mood: 'listening', key: 'listen' }),
        createElement(ActivityProbe, { mood: 'working', source: 'pass', key: 'pass' }),
        createElement(ActivityProbe, { mood: 'waiting', key: 'wait' }),
        createElement(ActivityProbe, { mood: 'blocked', key: 'block' }),
        createElement(ActivityProbe, { mood: 'thinking', source: 'request', key: 'req' }),
      ),
    );

    const getMood = () => container.querySelector('.face-box')?.getAttribute('data-mood');
    expect(getMood()).toBe('thinking');

    // Drop request -> blocked outranks waiting/pass/listening.
    rerender(
      createElement(
        FaceProvider,
        { trackPointer: false },
        createElement(FaceSlot, { slot: 'rail' }),
        createElement(ActivityProbe, { mood: 'listening', key: 'listen' }),
        createElement(ActivityProbe, { mood: 'working', source: 'pass', key: 'pass' }),
        createElement(ActivityProbe, { mood: 'waiting', key: 'wait' }),
        createElement(ActivityProbe, { mood: 'blocked', key: 'block' }),
      ),
    );
    expect(getMood()).toBe('blocked');

    // Drop blocked -> waiting outranks pass/listening.
    rerender(
      createElement(
        FaceProvider,
        { trackPointer: false },
        createElement(FaceSlot, { slot: 'rail' }),
        createElement(ActivityProbe, { mood: 'listening', key: 'listen' }),
        createElement(ActivityProbe, { mood: 'working', source: 'pass', key: 'pass' }),
        createElement(ActivityProbe, { mood: 'waiting', key: 'wait' }),
      ),
    );
    expect(getMood()).toBe('waiting');

    // Drop waiting -> pass outranks listening.
    rerender(
      createElement(
        FaceProvider,
        { trackPointer: false },
        createElement(FaceSlot, { slot: 'rail' }),
        createElement(ActivityProbe, { mood: 'listening', key: 'listen' }),
        createElement(ActivityProbe, { mood: 'working', source: 'pass', key: 'pass' }),
      ),
    );
    expect(getMood()).toBe('working');

    // Drop pass -> listening remains; drop listening -> idle.
    rerender(
      createElement(
        FaceProvider,
        { trackPointer: false },
        createElement(FaceSlot, { slot: 'rail' }),
        createElement(ActivityProbe, { mood: 'listening', key: 'listen' }),
      ),
    );
    expect(getMood()).toBe('listening');

    rerender(
      createElement(
        FaceProvider,
        { trackPointer: false },
        createElement(FaceSlot, { slot: 'rail' }),
      ),
    );
    expect(getMood()).toBe('idle');
  });

  it('hides rail FaceSlot during modal takeover and isolates modal work', () => {
    const { container, rerender } = renderDesk(
      createElement(
        'div',
        null,
        createElement(FaceSlot, { slot: 'rail' }),
        createElement(ActivityProbe, { mood: 'blocked', scope: 'global', key: 'g' }),
        createElement(FaceSlot, { slot: 'modal' }),
      ),
    );

    // Rail slot is hidden; modal holds the face with idle (ignoring global 'blocked').
    expect(container.querySelector('[data-face-slot="rail"]')).toBeNull();
    const modalFace = container.querySelector('[data-face-slot="modal"] .face-box');
    expect(modalFace).toHaveAttribute('data-mood', 'idle');

    // Modal activity drives the modal face.
    rerender(
      createElement(
        FaceProvider,
        { trackPointer: false },
        createElement(FaceSlot, { slot: 'rail' }),
        createElement(ActivityProbe, { mood: 'blocked', scope: 'global', key: 'g' }),
        createElement(FaceSlot, { slot: 'modal' }),
        createElement(ActivityProbe, { mood: 'working', scope: 'modal', stepIndex: 2, key: 'm' }),
      ),
    );
    expect(container.querySelector('[data-face-slot="modal"] .face-box')).toHaveAttribute(
      'data-mood',
      'working',
    );

    // Closing the modal restores the rail slot and the global mood.
    rerender(
      createElement(
        FaceProvider,
        { trackPointer: false },
        createElement(FaceSlot, { slot: 'rail' }),
        createElement(ActivityProbe, { mood: 'blocked', scope: 'global', key: 'g' }),
      ),
    );
    expect(container.querySelector('[data-face-slot="modal"]')).toBeNull();
    expect(container.querySelector('[data-face-slot="rail"] .face-box')).toHaveAttribute(
      'data-mood',
      'blocked',
    );
  });

  it('holds done happy arcs for ~1.6 s then returns to underlying mood', () => {
    vi.useFakeTimers();
    const { container, getByText } = renderDesk(
      createElement(
        'div',
        null,
        createElement(FaceSlot, { slot: 'rail' }),
        createElement(ActivityProbe, { mood: 'waiting' }),
        createElement(DoneTrigger, { label: 'Saved' }),
      ),
    );

    expect(container.querySelector('.face-box')).toHaveAttribute('data-mood', 'waiting');
    fireEvent.click(getByText('Finish'));
    expect(container.querySelector('.face-box')).toHaveAttribute('data-mood', 'done');
    expect(container.querySelector('.face-box')).toHaveAttribute('title', `${AGENT_NAME}: Saved`);

    act(() => {
      vi.advanceTimersByTime(DONE_DURATION_MS - 50);
    });
    expect(container.querySelector('.face-box')).toHaveAttribute('data-mood', 'done');

    act(() => {
      vi.advanceTimersByTime(60);
    });
    expect(container.querySelector('.face-box')).toHaveAttribute('data-mood', 'waiting');
  });

  it('safely renders FaceSlot and useFaceActivity outside FaceProvider', () => {
    function Isolated() {
      useFaceActivity({ mood: 'thinking' });
      return createElement(FaceSlot, { slot: 'rail' });
    }
    const { container } = render(createElement(Isolated));
    expect(container.querySelector('.face-box')).toHaveAttribute('data-mood', 'idle');
  });

  it('does not re-render activity consumers on pointermove or repeated identical lookTarget', () => {
    let activityRenders = 0;
    function StableConsumer() {
      activityRenders += 1;
      useFaceActivity({ mood: 'listening' });
      const actions = useFaceActions();
      return createElement(
        'button',
        {
          type: 'button',
          onClick: () => actions?.setLookTarget({ x: 120, y: 80 }),
        },
        'Set target',
      );
    }

    const { getByText } = render(
      createElement(
        FaceProvider,
        { trackPointer: true },
        createElement(FaceSlot, { slot: 'rail' }),
        createElement(StableConsumer),
      ),
    );

    expect(activityRenders).toBe(1);
    fireEvent(window, new MouseEvent('pointermove', { clientX: 50, clientY: 60 }));
    fireEvent(window, new MouseEvent('pointermove', { clientX: 90, clientY: 110 }));
    expect(activityRenders).toBe(1);

    fireEvent.click(getByText('Set target'));
    fireEvent.click(getByText('Set target'));
    expect(activityRenders).toBe(1);
  });

  it('keeps global and modal notifyDone timers isolated per scope', () => {
    vi.useFakeTimers();

    function GlobalDoneButton() {
      const ctx = useFaceContext();
      return createElement(
        'button',
        { type: 'button', onClick: () => ctx?.notifyDone('Global finished', 'global') },
        'Global Finish',
      );
    }

    const { container, getByText } = render(
      createElement(
        FaceProvider,
        { trackPointer: false },
        createElement(FaceSlot, { slot: 'modal' }),
        createElement(DoneTrigger, { label: 'Modal finished', scope: 'modal' }),
        createElement(GlobalDoneButton),
      ),
    );

    fireEvent.click(getByText('Finish'));
    fireEvent.click(getByText('Global Finish'));
    const modalFace = container.querySelector('[data-face-slot="modal"] .face-box');
    expect(modalFace).toHaveAttribute('data-mood', 'done');
    expect(modalFace).toHaveAttribute('title', `${AGENT_NAME}: Modal finished`);
  });
});

describe('face configuration presets and per-eye expression channels', () => {
  it('defines four distinct token-only presets with visor as default and resolves partial overrides', () => {
    expect(FACE_PRESET_IDS).toEqual(['companion', 'visor', 'instrument', 'pebble']);
    expect(DEFAULT_FACE_PRESET).toBe('visor');
    expect(ACTIVE_FACE_CONFIG.id).toBe('visor');

    const serialized = JSON.stringify(FACE_PRESETS);
    expect(serialized).not.toMatch(/#[0-9a-fA-F]{3,8}/);

    const custom = resolveFaceConfig({
      id: 'custom-visor',
      body: { fillToken: 'surface-2', borderToken: 'accent', radiusMd: 9 },
      eyes: { colorToken: 'accent', widthMd: 8 },
      moods: { idle: { tiltDeg: 3 } },
    });
    expect(custom.id).toBe('custom-visor');
    expect(custom.body.fillToken).toBe('surface-2');
    expect(custom.body.borderToken).toBe('accent');
    expect(custom.body.radiusMd).toBe(9);
    expect(custom.body.radiusSm).toBe(ACTIVE_FACE_CONFIG.body.radiusSm);
    expect(custom.eyes.colorToken).toBe('accent');
    expect(custom.eyes.widthMd).toBe(8);
    expect(custom.moods.idle.tiltDeg).toBe(3);
    expect(custom.moods.blocked.eyeShape).toBe('flat');
  });

  it('interpolates per-eye rotation and vertical offset smoothly across moods and presets', () => {
    const dom = makeDomElements();
    const sched = createFakeScheduler(0.5);
    const brain = createFaceBrain(dom, {
      clock: sched.clock,
      reducedMotion: false,
      config: FACE_PRESETS.pebble,
    });
    brain.start();
    expect(dom.leftEye.style.borderRadius).toBe('6px');

    // Thinking uses asymmetric eye height, offsetY, and rotation.
    brain.setMood('thinking');
    for (let i = 0; i < 30; i += 1) brain.step(30);
    expect(dom.leftEye.style.transform).not.toBe(dom.rightEye.style.transform);
    expect(dom.leftEye.style.transform).toContain('rotate(');

    // Working uses angled inward focus (+14deg / -14deg) monotonically.
    brain.setMood('working');
    let prevAngle = -Infinity;
    for (let i = 0; i < 20; i += 1) {
      brain.step(20);
      const m = /rotate\(([-\d.]+)deg\)/.exec(dom.leftEye.style.transform);
      const angle = m ? Number(m[1]) : 0;
      expect(angle).toBeGreaterThanOrEqual(prevAngle);
      expect(angle).toBeLessThanOrEqual(14.001);
      prevAngle = angle;
    }
    expect(prevAngle).toBeGreaterThan(12);
    expect(dom.rightEye.style.transform).toContain('rotate(-');

    // Blocked uses drooping outer-down flat bars (-14deg / +14deg).
    brain.setMood('blocked');
    for (let i = 0; i < 30; i += 1) brain.step(30);
    expect(dom.leftEye.style.transform).toContain('rotate(-');
    expect(dom.rightEye.style.transform).toContain('rotate(');
    expect(dom.leftEye.style.borderRadius).toBe('1px');

    // Switching config updates eye radius dynamically.
    brain.setMood('idle');
    for (let i = 0; i < 30; i += 1) brain.step(30);
    brain.setConfig(FACE_PRESETS.visor);
    for (let i = 0; i < 10; i += 1) brain.step(30);
    expect(dom.leftEye.style.borderRadius).toBe('2px');
    brain.destroy();
  });

  it('applies config CSS custom properties on AgentFace and flows through FaceProvider', () => {
    const { container } = render(
      createElement(
        FaceProvider,
        { trackPointer: false, config: FACE_PRESETS.instrument },
        createElement(FaceSlot, { slot: 'rail' }),
      ),
    );
    const face = container.querySelector('.face-box') as HTMLElement;
    expect(face).toHaveAttribute('data-preset', 'instrument');
    expect(face.style.getPropertyValue('--face-bg')).toBe('var(--surface-2)');
    expect(face.style.getPropertyValue('--face-border')).toBe('1px solid var(--rule-strong)');
    expect(face.style.getPropertyValue('--face-eye')).toBe('var(--accent)');
    expect(face.style.getPropertyValue('--face-eye-r')).toBe('3px');
  });
});
