import { ACTIVE_FACE_CONFIG, type FaceConfig } from './config';
import { type EyeShape, type FaceMood, type FacePose } from './moods';

/** Injectable clock and scheduler primitives so tests can drive time deterministically. */
export interface FaceClock {
  now: () => number;
  requestFrame?: (cb: (nowMs: number) => void) => number;
  cancelFrame?: (id: number) => void;
  setTimer?: (cb: () => void, ms: number) => number;
  clearTimer?: (id: number) => void;
  random?: () => number;
}

/** DOM elements controlled directly by the animation brain. */
export interface FaceElements {
  box: HTMLElement;
  leftEye: HTMLElement;
  rightEye: HTMLElement;
}

/** Configuration for createFaceBrain. */
export interface FaceBrainOptions {
  size?: 'md' | 'sm';
  mood?: FaceMood;
  stepIndex?: number;
  reducedMotion?: boolean;
  config?: FaceConfig;
  clock?: FaceClock;
}

/** Public snapshot returned by getState for diagnostics and assertions. */
export interface FaceBrainState {
  mood: FaceMood;
  stepIndex: number | undefined;
  reducedMotion: boolean;
  sleeping: boolean;
  running: boolean;
  hidden: boolean;
  pose: FacePose;
}

/** Controller interface for driving the face animation brain. */
export interface FaceBrain {
  start: () => void;
  destroy: () => void;
  setMood: (mood: FaceMood, opts?: { stepIndex?: number }) => void;
  setSize: (size: 'md' | 'sm') => void;
  setConfig: (nextConfig: FaceConfig) => void;
  setPointer: (x: number, y: number) => void;
  clearPointer: () => void;
  setLookTarget: (point: { x: number; y: number } | null) => void;
  setReducedMotion: (reduced: boolean) => void;
  setPaused: (paused: boolean) => void;
  triggerSquash: () => void;
  step: (dtMs: number) => void;
  tick: (nowMs: number) => void;
  getState: () => FaceBrainState;
}

const BLINK_CLOSE_MS = 75;
const BLINK_OPEN_MS = 95;
const CURIOUS_HOLD_MS = 1200;
const SQUASH_IMPULSE_MS = 90;
const EPSILON = 0.005;

/** Safe check for prefers-reduced-motion when jsdom omits matchMedia. */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Format a numeric CSS value to 3 decimal places without trailing noise. */
function fmt(value: number): string {
  const rounded = Math.round(value * 1000) / 1000;
  return Object.is(rounded, -0) ? '0' : String(rounded);
}

/** Exponential ease-out toward target with zero overshoot. */
function easeOut(current: number, target: number, speedPerSec: number, dtMs: number): number {
  if (dtMs <= 0) return current;
  const factor = 1 - Math.exp((-speedPerSec * dtMs) / 1000);
  const next = current + (target - current) * factor;
  return Math.abs(target - next) < EPSILON ? target : next;
}

/** True when two numbers match within settling epsilon. */
function near(a: number, b: number): boolean {
  return Math.abs(a - b) <= EPSILON;
}

/** Clone a pose object so mutations stay local. */
function clonePose(pose: FacePose): FacePose {
  return { ...pose };
}

/** Default browser clock backed by performance.now and requestAnimationFrame. */
function defaultClock(): Required<FaceClock> {
  return {
    now: () => (typeof performance !== 'undefined' ? performance.now() : Date.now()),
    requestFrame: (cb) => window.requestAnimationFrame(cb),
    cancelFrame: (id) => window.cancelAnimationFrame(id),
    setTimer: (cb, ms) => window.setTimeout(cb, ms),
    clearTimer: (id) => window.clearTimeout(id),
    random: () => Math.random(),
  };
}

/**
 * Create the single animation source for one AgentFace DOM instance.
 *
 * Uses frame-rate-independent exponential ease-out with zero overshoot,
 * sleeps with no active rAF loop once settled, and stops completely while
 * the document is hidden or prefers-reduced-motion is active.
 */
export function createFaceBrain(elements: FaceElements, options: FaceBrainOptions = {}): FaceBrain {
  const baseClock = defaultClock();
  const clock: Required<FaceClock> = {
    now: options.clock?.now ?? baseClock.now,
    requestFrame: options.clock?.requestFrame ?? baseClock.requestFrame,
    cancelFrame: options.clock?.cancelFrame ?? baseClock.cancelFrame,
    setTimer: options.clock?.setTimer ?? baseClock.setTimer,
    clearTimer: options.clock?.clearTimer ?? baseClock.clearTimer,
    random: options.clock?.random ?? baseClock.random,
  };

  let config: FaceConfig = options.config ?? ACTIVE_FACE_CONFIG;
  let size: 'md' | 'sm' = options.size ?? 'md';
  let mood: FaceMood = options.mood ?? 'idle';
  let stepIndex: number | undefined = options.stepIndex;
  let reducedMotion = options.reducedMotion ?? prefersReducedMotion();
  let paused = false;
  let started = false;
  let destroyed = false;

  let current = clonePose(config.moods[mood]);
  let pointer: { x: number; y: number } | null = null;
  let lookTarget: { x: number; y: number } | null = null;

  let simNowMs = clock.now();
  let moodStartMs = simNowMs;
  let lastTickMs = simNowMs;

  let rafId: number | null = null;
  let wakeTimerId: number | null = null;

  let blinkPhase: 'none' | 'closing' | 'opening' = 'none';
  let blinkEndsAt = 0;
  let nextBlinkAt = simNowMs + nextBlinkInterval();

  let driftOffset = { x: 0, y: 0 };
  let nextDriftAt = simNowMs + nextDriftInterval();

  let curiousEndsAt = 0;
  let curiousSide = 1;

  let squashEndsAt = 0;
  let stepPulseEndsAt = 0;

  /** Synchronize simulation time forward with the injected clock without rewinding. */
  function syncNow(): void {
    if (started) {
      simNowMs = Math.max(simNowMs, clock.now());
    }
  }

  /** Sample the next blink delay in [blinkMinMs, blinkMaxMs]. */
  function nextBlinkInterval(): number {
    const min = config.motion.blinkMinMs;
    const max = config.motion.blinkMaxMs;
    return min + clock.random() * (max - min);
  }

  /** Sample the next gaze drift delay in [driftMinMs, driftMaxMs]. */
  function nextDriftInterval(): number {
    const min = config.motion.driftMinMs;
    const max = config.motion.driftMaxMs;
    return min + clock.random() * (max - min);
  }

  /** Maximum eye travel distance in pixels for the current face size. */
  function maxTravel(): number {
    const base = config.motion.pointerMaxOffset;
    return size === 'sm' ? base * 0.75 : base;
  }

  /** True when the document is hidden in the current browser tab. */
  function isHidden(): boolean {
    return typeof document !== 'undefined' && document.visibilityState === 'hidden';
  }

  /** True when the current mood produces continuous motion over time. */
  function isContinuousMood(): boolean {
    return mood === 'thinking' || mood === 'reading' || mood === 'working';
  }

  /** True when the current mood supports autonomous blinking. */
  function allowsBlink(): boolean {
    return mood !== 'blocked' && mood !== 'done';
  }

  /** Cancel any queued animation frame. */
  function cancelPendingFrame(): void {
    if (rafId !== null) {
      clock.cancelFrame(rafId);
      rafId = null;
    }
  }

  /** Cancel any queued wake timer for blinks or gaze drifts. */
  function cancelWakeTimer(): void {
    if (wakeTimerId !== null) {
      clock.clearTimer(wakeTimerId);
      wakeTimerId = null;
    }
  }

  /** Read the face box center in viewport coordinates when layout exists. */
  function boxCenter(): { x: number; y: number } {
    const rect = elements.box.getBoundingClientRect();
    return {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    };
  }

  /** Compute eye offset toward a viewport coordinate, bounded by proximity if configured. */
  function vectorToPoint(
    point: { x: number; y: number },
    respectRadius: boolean,
  ): { x: number; y: number; tilt: number } | null {
    const center = boxCenter();
    const dx = point.x - center.x;
    const dy = point.y - center.y;
    const dist = Math.hypot(dx, dy);
    const radius = config.motion.pointerRangePx;
    if (respectRadius && dist > radius) return null;
    if (dist === 0) return { x: 0, y: 0, tilt: 0 };
    const travel = maxTravel();
    const strength = respectRadius
      ? Math.min(1, dist / 120) * (1 - (dist / radius) * 0.25)
      : Math.min(1, dist / 80);
    const ux = dx / dist;
    const uy = dy / dist;
    return {
      x: ux * travel * strength,
      y: uy * travel * strength,
      tilt: ux * 2.5 * strength,
    };
  }

  /** Compute the target pose for the given simulation timestamp. */
  function computeTarget(nowMs: number): FacePose {
    const base = config.moods[mood];
    const scale = size === 'sm' ? 0.75 : 1;
    const target: FacePose = {
      ...base,
      lookX: base.lookX * scale,
      lookY: base.lookY * scale,
      leftEyeOffsetY: base.leftEyeOffsetY * scale,
      rightEyeOffsetY: base.rightEyeOffsetY * scale,
    };

    if (reducedMotion) {
      if (mood === 'working' && typeof stepIndex === 'number') {
        const clamped = Math.max(0, Math.min(4, stepIndex));
        target.lookY = (-0.6 + clamped * 0.65) * scale;
      }
      return target;
    }

    const elapsed = Math.max(0, nowMs - moodStartMs);

    if (mood === 'idle') {
      if (pointer) {
        const vec = vectorToPoint(pointer, true);
        if (vec) {
          target.lookX = vec.x;
          target.lookY = vec.y;
          target.tiltDeg = vec.tilt;
        } else {
          target.lookX = driftOffset.x * scale;
          target.lookY = driftOffset.y * scale;
        }
      } else {
        target.lookX = driftOffset.x * scale;
        target.lookY = driftOffset.y * scale;
      }

      if (nowMs < curiousEndsAt && !pointer) {
        target.tiltDeg = curiousSide * 6;
        target.lookX = curiousSide * 2.1 * scale;
        target.lookY = -0.7 * scale;
        if (curiousSide > 0) {
          target.leftEyeScaleY = 0.78;
          target.rightEyeScaleY = 1.15;
          target.leftEyeOffsetY = 0.8 * scale;
          target.rightEyeOffsetY = -0.8 * scale;
        } else {
          target.leftEyeScaleY = 1.15;
          target.rightEyeScaleY = 0.78;
          target.leftEyeOffsetY = -0.8 * scale;
          target.rightEyeOffsetY = 0.8 * scale;
        }
      }
    } else if (mood === 'listening') {
      if (lookTarget) {
        const vec = vectorToPoint(lookTarget, false);
        if (vec) {
          target.lookX = vec.x;
          target.lookY = vec.y;
          target.tiltDeg = vec.tilt + 2;
        }
      }
    } else if (mood === 'thinking') {
      const phase = (elapsed % 2800) / 2800;
      target.lookX = (-2.2 + Math.sin(phase * Math.PI * 2) * 0.8) * scale;
      target.lookY = -2.5 * scale;
      target.tiltDeg = -6 + Math.sin(phase * Math.PI * 2) * 2;
    } else if (mood === 'reading') {
      const linePeriod = 1100;
      const lineIdx = Math.floor(elapsed / linePeriod) % 3;
      const lineProgress = (elapsed % linePeriod) / linePeriod;
      target.lookX = (-2.2 + lineProgress * 4.4) * scale;
      target.lookY = (-0.6 + lineIdx * 0.9) * scale;
    } else if (mood === 'working') {
      const wave = 0.5 - 0.5 * Math.cos((elapsed / 650) * Math.PI * 2);
      target.boxScaleX = 1 + 0.03 * wave;
      target.boxScaleY = 1 - 0.03 * wave;
      if (typeof stepIndex === 'number') {
        const clamped = Math.max(0, Math.min(4, stepIndex));
        target.lookX = (clamped % 2 === 0 ? -0.9 : 0.9) * scale;
        target.lookY = (-0.6 + clamped * 0.65) * scale;
      }
    }

    if (blinkPhase === 'closing') {
      target.leftEyeScaleY = 0.08;
      target.rightEyeScaleY = 0.08;
    }

    if (nowMs < squashEndsAt) {
      target.boxScaleX = 1.14;
      target.boxScaleY = 0.84;
    } else if (nowMs < stepPulseEndsAt) {
      target.boxScaleX = 1.06;
      target.boxScaleY = 0.94;
    }

    return target;
  }

  /** Apply CSS inline styles directly to the face box and eye elements. */
  function applyDom(): void {
    /** Map an EyeShape and optional pose radius override to a CSS border-radius value. */
    const borderRadiusFor = (shape: EyeShape, poseRadius?: number): string => {
      if (shape === 'flat') return '1px';
      if (shape === 'arc') return '99px 99px 4px 4px';
      if (shape === 'chevron') return '2px';
      if (typeof poseRadius === 'number') return `${fmt(poseRadius)}px`;
      return `${fmt(config.eyes.radius)}px`;
    };

    elements.leftEye.dataset.shape = current.eyeShape;
    elements.rightEye.dataset.shape = current.eyeShape;
    elements.leftEye.style.borderRadius = borderRadiusFor(current.eyeShape, current.leftEyeRadius);
    elements.rightEye.style.borderRadius = borderRadiusFor(current.eyeShape, current.rightEyeRadius);

    elements.leftEye.style.transform =
      `translate(${fmt(current.lookX)}px, ${fmt(current.lookY + current.leftEyeOffsetY)}px) ` +
      `rotate(${fmt(current.leftEyeRotateDeg)}deg) ` +
      `scale(${fmt(current.leftEyeScaleX)}, ${fmt(current.leftEyeScaleY)})`;
    elements.rightEye.style.transform =
      `translate(${fmt(current.lookX)}px, ${fmt(current.lookY + current.rightEyeOffsetY)}px) ` +
      `rotate(${fmt(current.rightEyeRotateDeg)}deg) ` +
      `scale(${fmt(current.rightEyeScaleX)}, ${fmt(current.rightEyeScaleY)})`;

    const isBoxIdentity =
      near(current.boxScaleX, 1) &&
      near(current.boxScaleY, 1) &&
      near(current.tiltDeg, 0);
    elements.box.style.transform = isBoxIdentity
      ? ''
      : `scale(${fmt(current.boxScaleX)}, ${fmt(current.boxScaleY)}) rotate(${fmt(current.tiltDeg)}deg)`;
  }

  /** True when current pose matches target within epsilon and no impulse is pending. */
  function isSettledAt(target: FacePose, nowMs: number): boolean {
    if (isContinuousMood() && !reducedMotion) return false;
    if (blinkPhase !== 'none') return false;
    if (nowMs < curiousEndsAt || nowMs < squashEndsAt || nowMs < stepPulseEndsAt) return false;
    return (
      near(current.lookX, target.lookX) &&
      near(current.lookY, target.lookY) &&
      near(current.leftEyeScaleX, target.leftEyeScaleX) &&
      near(current.leftEyeScaleY, target.leftEyeScaleY) &&
      near(current.rightEyeScaleX, target.rightEyeScaleX) &&
      near(current.rightEyeScaleY, target.rightEyeScaleY) &&
      near(current.leftEyeRotateDeg, target.leftEyeRotateDeg) &&
      near(current.rightEyeRotateDeg, target.rightEyeRotateDeg) &&
      near(current.leftEyeOffsetY, target.leftEyeOffsetY) &&
      near(current.rightEyeOffsetY, target.rightEyeOffsetY) &&
      near(current.boxScaleX, target.boxScaleX) &&
      near(current.boxScaleY, target.boxScaleY) &&
      near(current.tiltDeg, target.tiltDeg) &&
      current.eyeShape === target.eyeShape
    );
  }

  /** Advance autonomous blink/drift timers up to `nowMs`. */
  function advanceAutonomousEvents(nowMs: number): void {
    if (reducedMotion) return;

    if (blinkPhase === 'closing' && nowMs >= blinkEndsAt) {
      blinkPhase = 'opening';
      blinkEndsAt = nowMs + BLINK_OPEN_MS;
    } else if (blinkPhase === 'opening' && nowMs >= blinkEndsAt) {
      blinkPhase = 'none';
      nextBlinkAt = nowMs + nextBlinkInterval();
    }

    if (blinkPhase === 'none' && allowsBlink() && nowMs >= nextBlinkAt) {
      blinkPhase = 'closing';
      blinkEndsAt = nowMs + BLINK_CLOSE_MS;
    }

    if (mood === 'idle' && !pointer && nowMs >= nextDriftAt) {
      const r1 = clock.random();
      const r2 = clock.random();
      const r3 = clock.random();
      if (r1 < 0.3) {
        driftOffset = { x: 0, y: 0 };
      } else {
        driftOffset = {
          x: (r1 - 0.5) * 3.8,
          y: (r2 - 0.5) * 2.4,
        };
      }
      if (r3 < config.motion.curiousChance) {
        curiousSide = r2 >= 0.5 ? 1 : -1;
        curiousEndsAt = nowMs + CURIOUS_HOLD_MS;
      }
      nextDriftAt = nowMs + nextDriftInterval();
    }
  }

  /** Schedule a single timer wake-up for the next autonomous blink or drift. */
  function scheduleSleepWake(): void {
    cancelWakeTimer();
    if (!started || destroyed || paused || reducedMotion || isHidden()) return;
    syncNow();
    const candidates: number[] = [];
    if (allowsBlink()) candidates.push(nextBlinkAt);
    if (mood === 'idle' && !pointer) candidates.push(nextDriftAt);
    if (candidates.length === 0) return;
    const nextAt = Math.min(...candidates);
    const delay = Math.max(16, nextAt - simNowMs);
    wakeTimerId = clock.setTimer(() => {
      wakeTimerId = null;
      if (!started || destroyed || paused || reducedMotion || isHidden()) return;
      simNowMs = Math.max(simNowMs, clock.now());
      lastTickMs = simNowMs;
      advanceAutonomousEvents(simNowMs);
      scheduleNextFrame();
    }, delay);
  }

  /** Request one animation frame when motion is needed. */
  function scheduleNextFrame(): void {
    if (!started || destroyed || paused || reducedMotion || isHidden()) {
      cancelPendingFrame();
      return;
    }
    if (rafId !== null) return;
    rafId = clock.requestFrame((frameNow) => {
      rafId = null;
      if (!started || destroyed || paused || reducedMotion || isHidden()) return;
      tick(frameNow);
    });
  }

  /** Integrate the pose for `dtMs` at simulation time `simNowMs`. */
  function integrate(dtMs: number): void {
    if (reducedMotion) {
      current = computeTarget(simNowMs);
      applyDom();
      return;
    }

    advanceAutonomousEvents(simNowMs);
    const target = computeTarget(simNowMs);
    current.eyeShape = target.eyeShape;
    current.leftEyeRadius = target.leftEyeRadius;
    current.rightEyeRadius = target.rightEyeRadius;

    const baseRate = config.motion.easeRate;
    const eyeSpeed = blinkPhase !== 'none' ? baseRate * 2.2 : baseRate * 1.15;
    const gazeSpeed = mood === 'reading' ? baseRate * 1.4 : baseRate;
    const boxSpeed = simNowMs < squashEndsAt ? baseRate * 2 : baseRate;
    const tiltSpeed = baseRate * 0.85;

    current.lookX = easeOut(current.lookX, target.lookX, gazeSpeed, dtMs);
    current.lookY = easeOut(current.lookY, target.lookY, gazeSpeed, dtMs);
    current.leftEyeScaleX = easeOut(current.leftEyeScaleX, target.leftEyeScaleX, baseRate * 1.15, dtMs);
    current.leftEyeScaleY = easeOut(current.leftEyeScaleY, target.leftEyeScaleY, eyeSpeed, dtMs);
    current.rightEyeScaleX = easeOut(current.rightEyeScaleX, target.rightEyeScaleX, baseRate * 1.15, dtMs);
    current.rightEyeScaleY = easeOut(current.rightEyeScaleY, target.rightEyeScaleY, eyeSpeed, dtMs);
    current.leftEyeRotateDeg = easeOut(current.leftEyeRotateDeg, target.leftEyeRotateDeg, baseRate, dtMs);
    current.rightEyeRotateDeg = easeOut(current.rightEyeRotateDeg, target.rightEyeRotateDeg, baseRate, dtMs);
    current.leftEyeOffsetY = easeOut(current.leftEyeOffsetY, target.leftEyeOffsetY, baseRate, dtMs);
    current.rightEyeOffsetY = easeOut(current.rightEyeOffsetY, target.rightEyeOffsetY, baseRate, dtMs);
    current.boxScaleX = easeOut(current.boxScaleX, target.boxScaleX, boxSpeed, dtMs);
    current.boxScaleY = easeOut(current.boxScaleY, target.boxScaleY, boxSpeed, dtMs);
    current.tiltDeg = easeOut(current.tiltDeg, target.tiltDeg, tiltSpeed, dtMs);

    applyDom();
  }

  /** Wake the animation loop (or snap immediately under reduced motion). */
  function wake(): void {
    if (destroyed) return;
    syncNow();
    if (reducedMotion) {
      cancelPendingFrame();
      cancelWakeTimer();
      current = computeTarget(simNowMs);
      applyDom();
      return;
    }
    if (paused || isHidden()) {
      cancelPendingFrame();
      cancelWakeTimer();
      return;
    }
    cancelWakeTimer();
    if (started) {
      lastTickMs = simNowMs;
      scheduleNextFrame();
    }
  }

  /** Handle browser tab visibility transitions. */
  function onVisibilityChange(): void {
    if (isHidden()) {
      cancelPendingFrame();
      cancelWakeTimer();
      return;
    }
    if (started && !destroyed && !paused && !reducedMotion) {
      simNowMs = Math.max(simNowMs, clock.now());
      lastTickMs = simNowMs;
      if (nextBlinkAt <= simNowMs) nextBlinkAt = simNowMs + nextBlinkInterval();
      if (nextDriftAt <= simNowMs) nextDriftAt = simNowMs + nextDriftInterval();
      const target = computeTarget(simNowMs);
      if (!isSettledAt(target, simNowMs)) {
        scheduleNextFrame();
      } else {
        scheduleSleepWake();
      }
    }
  }

  /** Advance simulation by an explicit delta in milliseconds. */
  function step(dtMs: number): void {
    if (destroyed || dtMs < 0) return;
    simNowMs += dtMs;
    lastTickMs = simNowMs;
    integrate(dtMs);
  }

  /** Advance simulation to absolute timestamp `nowMs`. */
  function tick(nowMs: number): void {
    if (destroyed) return;
    const effectiveNow = Math.max(simNowMs, nowMs);
    const dtMs = Math.max(0, Math.min(100, effectiveNow - lastTickMs));
    simNowMs = effectiveNow;
    lastTickMs = effectiveNow;
    integrate(dtMs);

    const target = computeTarget(simNowMs);
    if (isSettledAt(target, simNowMs)) {
      cancelPendingFrame();
      scheduleSleepWake();
      return;
    }
    scheduleNextFrame();
  }

  /** Start observing visibility and running the brain loop. */
  function start(): void {
    if (started || destroyed) return;
    started = true;
    simNowMs = clock.now();
    lastTickMs = simNowMs;
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisibilityChange);
    }
    if (reducedMotion) {
      current = computeTarget(simNowMs);
      applyDom();
      return;
    }
    applyDom();
    if (!paused && !isHidden()) {
      if (isContinuousMood()) {
        scheduleNextFrame();
      } else {
        scheduleSleepWake();
      }
    }
  }

  /** Stop all frames, timers, and listeners permanently. */
  function destroy(): void {
    if (destroyed) return;
    destroyed = true;
    cancelPendingFrame();
    cancelWakeTimer();
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibilityChange);
    }
  }

  /** Set the active mood and optional DescribePlugin row step index. */
  function setMood(nextMood: FaceMood, opts?: { stepIndex?: number }): void {
    if (destroyed) return;
    syncNow();
    const prevMood = mood;
    const prevStep = stepIndex;
    mood = nextMood;
    stepIndex = opts?.stepIndex;
    if (prevMood !== nextMood) {
      moodStartMs = simNowMs;
      blinkPhase = 'none';
      curiousEndsAt = 0;
      if (nextMood === 'idle') {
        if (nextBlinkAt <= simNowMs) nextBlinkAt = simNowMs + nextBlinkInterval();
        if (nextDriftAt <= simNowMs) nextDriftAt = simNowMs + nextDriftInterval();
      }
    }
    if (nextMood === 'working' && typeof stepIndex === 'number' && stepIndex !== prevStep && !reducedMotion) {
      stepPulseEndsAt = simNowMs + 90;
    }
    if (reducedMotion) {
      current = computeTarget(simNowMs);
      applyDom();
      return;
    }
    wake();
  }

  /** Update the face box size scale ('md' = 32px, 'sm' = 24px). */
  function setSize(nextSize: 'md' | 'sm'): void {
    if (destroyed || size === nextSize) return;
    size = nextSize;
    if (reducedMotion) {
      current = computeTarget(simNowMs);
      applyDom();
    } else {
      wake();
    }
  }

  /** Apply a new FaceConfig dynamically without recreating the brain. */
  function setConfig(nextConfig: FaceConfig): void {
    if (destroyed || config === nextConfig) return;
    config = nextConfig;
    if (reducedMotion) {
      current = computeTarget(simNowMs);
      applyDom();
    } else {
      wake();
    }
  }

  /** Update viewport pointer coordinates for proximity eye-tracking. */
  function setPointer(x: number, y: number): void {
    if (destroyed) return;
    pointer = { x, y };
    if (!reducedMotion && mood === 'idle') wake();
  }

  /** Clear pointer proximity tracking. */
  function clearPointer(): void {
    if (destroyed || !pointer) return;
    pointer = null;
    if (!reducedMotion && mood === 'idle') wake();
  }

  /** Set or clear an explicit viewport gaze target (e.g. the command bar). */
  function setLookTarget(point: { x: number; y: number } | null): void {
    if (destroyed) return;
    lookTarget = point;
    if (!reducedMotion && mood === 'listening') wake();
  }

  /** Enable or disable reduced-motion mode dynamically. */
  function setReducedMotion(reduced: boolean): void {
    if (destroyed || reducedMotion === reduced) return;
    reducedMotion = reduced;
    if (reduced) {
      blinkPhase = 'none';
      curiousEndsAt = 0;
      squashEndsAt = 0;
      stepPulseEndsAt = 0;
      cancelPendingFrame();
      cancelWakeTimer();
      current = computeTarget(simNowMs);
      applyDom();
    } else {
      wake();
    }
  }

  /** Pause or resume scheduling (used when a slot is temporarily inactive). */
  function setPaused(nextPaused: boolean): void {
    if (destroyed || paused === nextPaused) return;
    paused = nextPaused;
    if (paused) {
      cancelPendingFrame();
      cancelWakeTimer();
    } else {
      wake();
    }
  }

  /** Trigger a brief playful squash impulse on click and nothing else. */
  function triggerSquash(): void {
    if (reducedMotion || destroyed) return;
    syncNow();
    squashEndsAt = simNowMs + SQUASH_IMPULSE_MS;
    wake();
  }

  /** Return a diagnostic snapshot of the current brain state. */
  function getState(): FaceBrainState {
    const target = computeTarget(simNowMs);
    return {
      mood,
      stepIndex,
      reducedMotion,
      sleeping: rafId === null && isSettledAt(target, simNowMs),
      running: rafId !== null,
      hidden: isHidden(),
      pose: clonePose(current),
    };
  }

  return {
    start,
    destroy,
    setMood,
    setSize,
    setConfig,
    setPointer,
    clearPointer,
    setLookTarget,
    setReducedMotion,
    setPaused,
    triggerSquash,
    step,
    tick,
    getState,
  };
}
