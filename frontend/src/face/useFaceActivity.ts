import { useEffect, useId } from 'react';
import { useFaceActions, type FaceScope } from './FaceProvider';
import type { FaceActivitySource, FaceMood } from './moods';

/** Options accepted by useFaceActivity. */
export interface UseFaceActivityOptions {
  /** Mood to report while active. */
  mood: FaceMood;
  /** Optional status label shown in the face tooltip. */
  label?: string;
  /** 'request' for user-initiated foreground work, 'pass' for background work. */
  source?: FaceActivitySource;
  /** 'global' (default) or 'modal' (drives the face during modal takeover). */
  scope?: FaceScope;
  /** Optional row index for stepping focus (e.g. DescribePlugin). */
  stepIndex?: number;
  /** Set false to pause/withdraw this activity without unmounting. Default true. */
  active?: boolean;
}

/**
 * Report an activity to FaceProvider with automatic cleanup on unmount.
 *
 * Safe no-op when rendered outside FaceProvider so isolated component tests
 * continue to work without wrapping.
 */
export function useFaceActivity({
  mood,
  label,
  source,
  scope = 'global',
  stepIndex,
  active = true,
}: UseFaceActivityOptions): void {
  const id = useId();
  const actions = useFaceActions();
  const setActivity = actions?.setActivity;
  const removeActivity = actions?.removeActivity;

  useEffect(() => {
    if (!setActivity || !removeActivity) return undefined;
    if (!active) {
      removeActivity(id);
      return undefined;
    }
    setActivity({ id, mood, label, source, scope, stepIndex });
    return () => {
      removeActivity(id);
    };
  }, [id, setActivity, removeActivity, active, mood, label, source, scope, stepIndex]);
}
