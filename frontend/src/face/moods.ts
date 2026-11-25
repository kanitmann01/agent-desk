import { AGENT_NAME } from './name';

/** The eight expressions the agent face can hold. */
export type FaceMood =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'reading'
  | 'working'
  | 'waiting'
  | 'blocked'
  | 'done';

/** All eight moods in display order for the review sheet and tests. */
export const FACE_MOODS: readonly FaceMood[] = [
  'idle',
  'listening',
  'thinking',
  'reading',
  'working',
  'waiting',
  'blocked',
  'done',
] as const;

/** Priority tiers resolved by FaceProvider, highest first. */
export type FacePriority =
  | 'request'
  | 'done'
  | 'blocked'
  | 'waiting'
  | 'pass'
  | 'listening'
  | 'idle';

/** Ordered priority table from highest precedence to lowest. */
export const FACE_PRIORITY_ORDER: readonly FacePriority[] = [
  'request',
  'done',
  'blocked',
  'waiting',
  'pass',
  'listening',
  'idle',
] as const;

/** Activity source classification for work moods. */
export type FaceActivitySource = 'request' | 'pass';

/** Eye silhouette shape rendered by CSS and brain DOM updates. */
export type EyeShape = 'capsule' | 'flat' | 'arc' | 'chevron';

/** Target pose values used by the animation brain and reduced-motion mode. */
export interface FacePose {
  lookX: number;
  lookY: number;
  leftEyeScaleX: number;
  leftEyeScaleY: number;
  rightEyeScaleX: number;
  rightEyeScaleY: number;
  leftEyeRotateDeg: number;
  rightEyeRotateDeg: number;
  leftEyeOffsetY: number;
  rightEyeOffsetY: number;
  leftEyeRadius?: number;
  rightEyeRadius?: number;
  boxScaleX: number;
  boxScaleY: number;
  tiltDeg: number;
  eyeShape: EyeShape;
}

/** Static target pose (and reduced-motion still pose) for each mood. */
export const MOOD_POSES: Record<FaceMood, FacePose> = {
  idle: {
    lookX: 0,
    lookY: 0,
    leftEyeScaleX: 1,
    leftEyeScaleY: 1,
    rightEyeScaleX: 1,
    rightEyeScaleY: 1,
    leftEyeRotateDeg: 0,
    rightEyeRotateDeg: 0,
    leftEyeOffsetY: 0,
    rightEyeOffsetY: 0,
    boxScaleX: 1,
    boxScaleY: 1,
    tiltDeg: 0,
    eyeShape: 'capsule',
  },
  listening: {
    lookX: 2.2,
    lookY: -0.6,
    leftEyeScaleX: 1.22,
    leftEyeScaleY: 1.28,
    rightEyeScaleX: 1.22,
    rightEyeScaleY: 1.28,
    leftEyeRotateDeg: 0,
    rightEyeRotateDeg: 0,
    leftEyeOffsetY: -0.4,
    rightEyeOffsetY: -0.4,
    boxScaleX: 1.02,
    boxScaleY: 1.02,
    tiltDeg: 4,
    eyeShape: 'capsule',
  },
  thinking: {
    lookX: -2.5,
    lookY: -2.5,
    leftEyeScaleX: 1.05,
    leftEyeScaleY: 0.42,
    rightEyeScaleX: 1.08,
    rightEyeScaleY: 1.18,
    leftEyeRotateDeg: -4,
    rightEyeRotateDeg: 4,
    leftEyeOffsetY: 1.5,
    rightEyeOffsetY: -1.5,
    boxScaleX: 1,
    boxScaleY: 1,
    tiltDeg: -6,
    eyeShape: 'capsule',
  },
  reading: {
    lookX: -2.0,
    lookY: 0.2,
    leftEyeScaleX: 1.15,
    leftEyeScaleY: 0.52,
    rightEyeScaleX: 1.15,
    rightEyeScaleY: 0.52,
    leftEyeRotateDeg: 0,
    rightEyeRotateDeg: 0,
    leftEyeOffsetY: 0,
    rightEyeOffsetY: 0,
    leftEyeRadius: 2,
    rightEyeRadius: 2,
    boxScaleX: 1,
    boxScaleY: 1,
    tiltDeg: 0,
    eyeShape: 'capsule',
  },
  working: {
    lookX: 0,
    lookY: 1.2,
    leftEyeScaleX: 1.08,
    leftEyeScaleY: 0.68,
    rightEyeScaleX: 1.08,
    rightEyeScaleY: 0.68,
    leftEyeRotateDeg: 14,
    rightEyeRotateDeg: -14,
    leftEyeOffsetY: 0,
    rightEyeOffsetY: 0,
    leftEyeRadius: 2,
    rightEyeRadius: 2,
    boxScaleX: 1.02,
    boxScaleY: 0.98,
    tiltDeg: 0,
    eyeShape: 'capsule',
  },
  waiting: {
    lookX: 0,
    lookY: -2.8,
    leftEyeScaleX: 1.1,
    leftEyeScaleY: 1.28,
    rightEyeScaleX: 1.1,
    rightEyeScaleY: 1.28,
    leftEyeRotateDeg: 0,
    rightEyeRotateDeg: 0,
    leftEyeOffsetY: 0,
    rightEyeOffsetY: 0,
    boxScaleX: 1,
    boxScaleY: 1,
    tiltDeg: 0,
    eyeShape: 'capsule',
  },
  blocked: {
    lookX: 0,
    lookY: 0.8,
    leftEyeScaleX: 1.3,
    leftEyeScaleY: 0.28,
    rightEyeScaleX: 1.3,
    rightEyeScaleY: 0.28,
    leftEyeRotateDeg: -14,
    rightEyeRotateDeg: 14,
    leftEyeOffsetY: 0,
    rightEyeOffsetY: 0,
    boxScaleX: 1,
    boxScaleY: 1,
    tiltDeg: 0,
    eyeShape: 'flat',
  },
  done: {
    lookX: 0,
    lookY: -0.6,
    leftEyeScaleX: 1.5,
    leftEyeScaleY: 0.56,
    rightEyeScaleX: 1.5,
    rightEyeScaleY: 0.56,
    leftEyeRotateDeg: 0,
    rightEyeRotateDeg: 0,
    leftEyeOffsetY: 0,
    rightEyeOffsetY: 0,
    boxScaleX: 1,
    boxScaleY: 1,
    tiltDeg: 0,
    eyeShape: 'arc',
  },
};

/** Default short status text per mood when no custom label is provided. */
export const MOOD_DEFAULT_LABELS: Record<FaceMood, string> = {
  idle: 'Ready',
  listening: 'Listening',
  thinking: 'Thinking',
  reading: 'Reading',
  working: 'Working',
  waiting: 'Waiting for you',
  blocked: 'Needs attention',
  done: 'Done',
};

/** Duration in milliseconds that a transient done expression holds. */
export const DONE_DURATION_MS = 1600;

/**
 * Format the native hover tooltip string using AGENT_NAME and an optional status label.
 */
export function formatFaceTooltip(mood: FaceMood, label?: string): string {
  const trimmed = label?.trim();
  if (trimmed) return `${AGENT_NAME}: ${trimmed}`;
  if (mood === 'idle') return AGENT_NAME;
  return `${AGENT_NAME}: ${MOOD_DEFAULT_LABELS[mood]}`;
}

/**
 * Map a mood and optional source to a tier in FACE_PRIORITY_ORDER.
 */
export function resolveActivityPriority(
  mood: FaceMood,
  source?: FaceActivitySource,
): FacePriority {
  if (mood === 'done') return 'done';
  if (mood === 'blocked') return 'blocked';
  if (mood === 'waiting') return 'waiting';
  if (
    source === 'request' &&
    (mood === 'thinking' || mood === 'reading' || mood === 'working')
  ) {
    return 'request';
  }
  if (source === 'pass') return 'pass';
  if (mood === 'thinking' || mood === 'reading' || mood === 'working') return 'pass';
  if (mood === 'listening') return 'listening';
  return 'idle';
}

/**
 * Compare two priorities; negative means `a` outranks `b`.
 */
export function comparePriority(a: FacePriority, b: FacePriority): number {
  return FACE_PRIORITY_ORDER.indexOf(a) - FACE_PRIORITY_ORDER.indexOf(b);
}
