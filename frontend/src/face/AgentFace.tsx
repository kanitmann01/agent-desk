import { useEffect, useMemo, useRef, type CSSProperties } from 'react';
import { createFaceBrain, type FaceBrain, type FaceClock } from './brain';
import { ACTIVE_FACE_CONFIG, type FaceConfig } from './config';
import { formatFaceTooltip, type FaceMood } from './moods';

/** Props for the decorative AgentFace component. */
export interface AgentFaceProps {
  /** 'md' renders 32px (default); 'sm' renders 24px. */
  size?: 'md' | 'sm';
  /** Active facial mood. */
  mood?: FaceMood;
  /** Optional status phrase appended to the native tooltip. */
  label?: string;
  /** Optional row index for stepping focus (e.g. DescribePlugin). */
  stepIndex?: number;
  /** Force reduced-motion static pose (used in tests and review sheet). */
  reducedMotion?: boolean;
  /** Pause animation scheduling while hidden. */
  paused?: boolean;
  /** Viewport coordinates for the command bar or active input field. */
  lookTarget?: { x: number; y: number } | null;
  /** Viewport pointer coordinates for proximity eye-tracking. */
  pointer?: { x: number; y: number } | null;
  /** Optional ref-backed pointer subscription (avoids React re-renders on pointermove). */
  subscribePointer?: (listener: (point: { x: number; y: number } | null) => void) => () => void;
  /** Optional personality & token config override (defaults to ACTIVE_FACE_CONFIG). */
  config?: FaceConfig;
  /** Optional clock override for deterministic tests. */
  clock?: FaceClock;
  /** Optional extra CSS class name. */
  className?: string;
  /** Optional callback exposing the underlying brain for tests. */
  onBrainReady?: (brain: FaceBrain | null) => void;
}

/** Map a FaceConfig and size variant to token-only CSS custom properties. */
function buildFaceVars(config: FaceConfig, size: 'md' | 'sm'): CSSProperties {
  const isSm = size === 'sm';
  const baseH = isSm ? 24 : 32;
  const baseW = Math.round(baseH * config.body.aspectRatio);
  const boxRadius = isSm ? config.body.radiusSm : config.body.radiusMd;
  const eyeW = isSm ? config.eyes.widthSm : config.eyes.widthMd;
  const eyeH = isSm ? config.eyes.heightSm : config.eyes.heightMd;
  const eyeGap = isSm ? config.eyes.gapSm : config.eyes.gapMd;
  const border =
    config.body.borderToken === 'none'
      ? 'none'
      : `1px solid var(--${config.body.borderToken})`;

  return {
    '--face-bg': `var(--${config.body.fillToken})`,
    '--face-border': border,
    '--face-radius': `${boxRadius}px`,
    '--face-w': `${baseW}px`,
    '--face-h': `${baseH}px`,
    '--face-eye': `var(--${config.eyes.colorToken})`,
    '--face-eye-w': `${eyeW}px`,
    '--face-eye-h': `${eyeH}px`,
    '--face-eye-gap': `${eyeGap}px`,
    '--face-eye-r': `${config.eyes.radius}px`,
  } as CSSProperties;
}

/**
 * Decorative agent face with two expressive eyes and no mouth.
 *
 * Always `aria-hidden="true"`, non-focusable, and excluded from Tab order.
 * Exposes a native `title` tooltip on hover and squashes playfully on click.
 */
export default function AgentFace({
  size = 'md',
  mood = 'idle',
  label,
  stepIndex,
  reducedMotion,
  paused = false,
  lookTarget = null,
  pointer = null,
  subscribePointer,
  config = ACTIVE_FACE_CONFIG,
  clock,
  className,
  onBrainReady,
}: AgentFaceProps) {
  const boxRef = useRef<HTMLSpanElement>(null);
  const leftEyeRef = useRef<HTMLSpanElement>(null);
  const rightEyeRef = useRef<HTMLSpanElement>(null);
  const brainRef = useRef<FaceBrain | null>(null);
  const onBrainReadyRef = useRef(onBrainReady);
  onBrainReadyRef.current = onBrainReady;

  useEffect(() => {
    const box = boxRef.current;
    const leftEye = leftEyeRef.current;
    const rightEye = rightEyeRef.current;
    if (!box || !leftEye || !rightEye) return undefined;

    const brain = createFaceBrain(
      { box, leftEye, rightEye },
      { size, mood, stepIndex, reducedMotion, config, clock },
    );
    brainRef.current = brain;
    brain.start();
    onBrainReadyRef.current?.(brain);

    return () => {
      onBrainReadyRef.current?.(null);
      brain.destroy();
      brainRef.current = null;
    };
    // Brain lifecycle is tied to mount and clock injection; dynamic props sync below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clock]);

  useEffect(() => {
    brainRef.current?.setSize(size);
  }, [size]);

  useEffect(() => {
    brainRef.current?.setConfig(config);
  }, [config]);

  useEffect(() => {
    brainRef.current?.setMood(mood, { stepIndex });
  }, [mood, stepIndex]);

  useEffect(() => {
    if (typeof reducedMotion === 'boolean') {
      brainRef.current?.setReducedMotion(reducedMotion);
    }
  }, [reducedMotion]);

  useEffect(() => {
    brainRef.current?.setPaused(paused);
  }, [paused]);

  useEffect(() => {
    brainRef.current?.setLookTarget(lookTarget);
  }, [lookTarget]);

  useEffect(() => {
    if (subscribePointer) {
      return subscribePointer((point) => {
        if (point) {
          brainRef.current?.setPointer(point.x, point.y);
        } else {
          brainRef.current?.clearPointer();
        }
      });
    }
    if (pointer) {
      brainRef.current?.setPointer(pointer.x, pointer.y);
    } else {
      brainRef.current?.clearPointer();
    }
    return undefined;
  }, [pointer, subscribePointer]);

  const faceVars = useMemo(() => buildFaceVars(config, size), [config, size]);
  const tooltip = formatFaceTooltip(mood, label);
  const classes = ['face-box', size === 'sm' ? 'face-sm' : 'face-md', className]
    .filter(Boolean)
    .join(' ');

  return (
    <span
      ref={boxRef}
      className={classes}
      style={faceVars}
      data-mood={mood}
      data-size={size}
      data-preset={config.id}
      aria-hidden="true"
      title={tooltip}
      onClick={() => brainRef.current?.triggerSquash()}
    >
      <span className="face-eyes">
        <span ref={leftEyeRef} className="face-eye face-eye-left" />
        <span ref={rightEyeRef} className="face-eye face-eye-right" />
      </span>
    </span>
  );
}
