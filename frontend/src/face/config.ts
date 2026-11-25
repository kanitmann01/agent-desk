import { MOOD_POSES, type FaceMood, type FacePose } from './moods';

/** Semantic CSS color token names allowed for the face body fill. */
export type FaceBodyFillToken =
  | 'heading'
  | 'surface'
  | 'surface-2'
  | 'surface-3'
  | 'canvas'
  | 'accent';

/** Semantic CSS border token names allowed for the face body outline. */
export type FaceBodyBorderToken = 'none' | 'rule' | 'rule-strong' | 'accent' | 'heading';

/** Semantic CSS color token names allowed for the face eyes. */
export type FaceEyeColorToken = 'canvas' | 'heading' | 'accent' | 'text';

/** Built-in character personality preset identifiers. */
export type FacePresetId = 'companion' | 'visor' | 'instrument' | 'pebble';

/** Default active preset id for the desk. */
export const DEFAULT_FACE_PRESET: FacePresetId = 'visor';

/** Ordered list of built-in personality presets for UI pickers and comparison matrices. */
export const FACE_PRESET_IDS: readonly FacePresetId[] = [
  'companion',
  'visor',
  'instrument',
  'pebble',
] as const;

/** Body geometry and theme-token styling for the agent face container. */
export interface FaceBodyConfig {
  fillToken: FaceBodyFillToken;
  borderToken: FaceBodyBorderToken;
  radiusMd: number;
  radiusSm: number;
  aspectRatio: number;
}

/** Eye geometry and theme-token color configuration. */
export interface FaceEyesConfig {
  colorToken: FaceEyeColorToken;
  widthMd: number;
  heightMd: number;
  gapMd: number;
  widthSm: number;
  heightSm: number;
  gapSm: number;
  radius: number;
}

/** Motion timing, autonomous behavior, and pointer-tracking parameters. */
export interface FaceMotionConfig {
  easeRate: number;
  blinkMinMs: number;
  blinkMaxMs: number;
  driftMinMs: number;
  driftMaxMs: number;
  curiousChance: number;
  doneDurationMs: number;
  pointerMaxOffset: number;
  pointerRangePx: number;
}

/**
 * Complete user-editable configuration for the agent face.
 *
 * All colors reference semantic CSS tokens (`var(--...)`) with zero hex literals
 * so every preset adapts automatically across Unkey, Coforge, and Momentuum.
 */
export interface FaceConfig {
  id: string;
  label: string;
  description: string;
  body: FaceBodyConfig;
  eyes: FaceEyesConfig;
  motion: FaceMotionConfig;
  moods: Record<FaceMood, FacePose>;
}

/** Partial override shape accepted by resolveFaceConfig. */
export interface FaceConfigOverride {
  id?: string;
  label?: string;
  description?: string;
  body?: Partial<FaceBodyConfig>;
  eyes?: Partial<FaceEyesConfig>;
  motion?: Partial<FaceMotionConfig>;
  moods?: Partial<Record<FaceMood, Partial<FacePose>>>;
}

const DEFAULT_MOTION: FaceMotionConfig = {
  easeRate: 14,
  blinkMinMs: 3000,
  blinkMaxMs: 6000,
  driftMinMs: 2000,
  driftMaxMs: 4000,
  curiousChance: 0.25,
  doneDurationMs: 1600,
  pointerMaxOffset: 2.8,
  pointerRangePx: 380,
};

/** Clone the base mood pose table with optional per-mood overrides. */
function buildMoods(
  overrides: Partial<Record<FaceMood, Partial<FacePose>>> = {},
): Record<FaceMood, FacePose> {
  const out = {} as Record<FaceMood, FacePose>;
  for (const key of Object.keys(MOOD_POSES) as FaceMood[]) {
    out[key] = { ...MOOD_POSES[key], ...(overrides[key] ?? {}) };
  }
  return out;
}

/**
 * Four distinct non-Grok-Bot character personalities for Agent Desk.
 *
 * Each preset keeps full three-theme token contrast while varying body silhouette,
 * resting eye geometry, and signature idle attitude.
 */
export const FACE_PRESETS: Record<FacePresetId, FaceConfig> = {
  companion: {
    id: 'companion',
    label: 'Companion',
    description: 'Rounded square with wide-set expressive squircle eyes.',
    body: {
      fillToken: 'heading',
      borderToken: 'none',
      radiusMd: 10,
      radiusSm: 8,
      aspectRatio: 1,
    },
    eyes: {
      colorToken: 'canvas',
      widthMd: 6,
      heightMd: 8,
      gapMd: 6,
      widthSm: 4.5,
      heightSm: 6,
      gapSm: 4.5,
      radius: 4,
    },
    motion: { ...DEFAULT_MOTION },
    moods: buildMoods(),
  },
  visor: {
    id: 'visor',
    label: 'Visor',
    description: 'Soft squircle with crisp rectangular-rounded visor eyes.',
    body: {
      fillToken: 'heading',
      borderToken: 'none',
      radiusMd: 11,
      radiusSm: 8,
      aspectRatio: 1,
    },
    eyes: {
      colorToken: 'canvas',
      widthMd: 7,
      heightMd: 6,
      gapMd: 5,
      widthSm: 5.5,
      heightSm: 4.5,
      gapSm: 4,
      radius: 2,
    },
    motion: { ...DEFAULT_MOTION, easeRate: 16 },
    moods: buildMoods({
      idle: { leftEyeScaleY: 0.96, rightEyeScaleY: 0.96 },
      reading: {
        leftEyeScaleX: 1.12,
        rightEyeScaleX: 1.12,
        leftEyeScaleY: 0.56,
        rightEyeScaleY: 0.56,
      },
      done: { leftEyeScaleX: 1.36, rightEyeScaleX: 1.36 },
    }),
  },
  instrument: {
    id: 'instrument',
    label: 'Instrument',
    description: 'Native 1px bento cell with accent-colored eyes matching the desk.',
    body: {
      fillToken: 'surface-2',
      borderToken: 'rule-strong',
      radiusMd: 8,
      radiusSm: 6,
      aspectRatio: 1,
    },
    eyes: {
      colorToken: 'accent',
      widthMd: 6,
      heightMd: 7,
      gapMd: 6,
      widthSm: 4.5,
      heightSm: 5.5,
      gapSm: 4.5,
      radius: 3,
    },
    motion: { ...DEFAULT_MOTION, easeRate: 15 },
    moods: buildMoods(),
  },
  pebble: {
    id: 'pebble',
    label: 'Pebble',
    description: 'Soft 12px square with friendly geometric dot eyes that morph per mood.',
    body: {
      fillToken: 'heading',
      borderToken: 'none',
      radiusMd: 12,
      radiusSm: 9,
      aspectRatio: 1,
    },
    eyes: {
      colorToken: 'canvas',
      widthMd: 6,
      heightMd: 6,
      gapMd: 6,
      widthSm: 4.5,
      heightSm: 4.5,
      gapSm: 4.5,
      radius: 6,
    },
    motion: { ...DEFAULT_MOTION, curiousChance: 0.3 },
    moods: buildMoods({
      listening: {
        leftEyeScaleX: 1.24,
        leftEyeScaleY: 1.32,
        rightEyeScaleX: 1.24,
        rightEyeScaleY: 1.32,
      },
      reading: { leftEyeRadius: 2, rightEyeRadius: 2 },
      working: { leftEyeRadius: 2, rightEyeRadius: 2 },
    }),
  },
};

/** Default active configuration shipped by the desk (edit or override via resolveFaceConfig). */
export const ACTIVE_FACE_CONFIG: FaceConfig = FACE_PRESETS[DEFAULT_FACE_PRESET];

/**
 * Resolve a complete FaceConfig from a base config/preset and optional partial overrides.
 */
export function resolveFaceConfig(
  override?: FacePresetId | FaceConfigOverride,
  base: FaceConfig = ACTIVE_FACE_CONFIG,
): FaceConfig {
  if (!override) return base;
  if (typeof override === 'string') return FACE_PRESETS[override];
  return {
    id: override.id ?? base.id,
    label: override.label ?? base.label,
    description: override.description ?? base.description,
    body: { ...base.body, ...(override.body ?? {}) },
    eyes: { ...base.eyes, ...(override.eyes ?? {}) },
    motion: { ...base.motion, ...(override.motion ?? {}) },
    moods: buildMoods(
      Object.fromEntries(
        (Object.keys(base.moods) as FaceMood[]).map((m) => [
          m,
          { ...base.moods[m], ...(override.moods?.[m] ?? {}) },
        ]),
      ),
    ),
  };
}
