import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { ACTIVE_FACE_CONFIG, type FaceConfig } from './config';
import {
  comparePriority,
  resolveActivityPriority,
  type FaceActivitySource,
  type FaceMood,
} from './moods';

/** Scope of an activity: global desk/rail vs active modal takeover. */
export type FaceScope = 'global' | 'modal';

/** Viewport coordinate pair. */
export interface FacePoint {
  x: number;
  y: number;
}

/** One reported activity entry held in FaceProvider. */
export interface FaceActivityEntry {
  id: string;
  mood: FaceMood;
  label?: string;
  source?: FaceActivitySource;
  scope: FaceScope;
  stepIndex?: number;
  updatedAt: number;
}

/** Resolved face state consumed by FaceSlot. */
export interface ResolvedFaceState {
  mood: FaceMood;
  label?: string;
  stepIndex?: number;
  hasModalSlot: boolean;
  lookTarget: FacePoint | null;
  config: FaceConfig;
}

/** Identity-stable action callbacks exposed by FaceProvider. */
export interface FaceActionsValue {
  setActivity: (entry: Omit<FaceActivityEntry, 'updatedAt'>) => void;
  removeActivity: (id: string) => void;
  notifyDone: (label?: string, scope?: FaceScope) => void;
  registerModalSlot: (id: string) => void;
  unregisterModalSlot: (id: string) => void;
  setLookTarget: (point: FacePoint | null) => void;
  subscribePointer: (listener: (point: FacePoint | null) => void) => () => void;
}

/** Combined context shape returned by useFaceContext for convenience. */
export interface FaceContextValue extends FaceActionsValue {
  state: ResolvedFaceState;
}

const FaceStateContext = createContext<ResolvedFaceState | null>(null);
const FaceActionsContext = createContext<FaceActionsValue | null>(null);

/** Props for FaceProvider. */
export interface FaceProviderProps {
  children?: ReactNode;
  /** Disable global window pointer tracking (useful in focused tests). */
  trackPointer?: boolean;
  /** Optional personality & token configuration (defaults to ACTIVE_FACE_CONFIG). */
  config?: FaceConfig;
  /** Override the done hold duration in milliseconds (default config.motion.doneDurationMs). */
  doneDurationMs?: number;
}

/** Pick the highest-priority active entry for the given scope. */
function resolveForScope(
  entries: Map<string, FaceActivityEntry>,
  scope: FaceScope,
): { mood: FaceMood; label?: string; stepIndex?: number } {
  let winner: FaceActivityEntry | null = null;
  let winnerPriority = resolveActivityPriority('idle');

  for (const entry of entries.values()) {
    if (entry.scope !== scope) continue;
    const priority = resolveActivityPriority(entry.mood, entry.source);
    if (!winner) {
      winner = entry;
      winnerPriority = priority;
      continue;
    }
    const cmp = comparePriority(priority, winnerPriority);
    if (cmp < 0 || (cmp === 0 && entry.updatedAt >= winner.updatedAt)) {
      winner = entry;
      winnerPriority = priority;
    }
  }

  if (!winner) return { mood: 'idle' };
  return {
    mood: winner.mood,
    label: winner.label,
    stepIndex: winner.stepIndex,
  };
}

/**
 * Global coordinator for the agent face mood, modal takeover, and pointer gaze.
 *
 * Actions live in a separate context from state so callers (useFaceActivity,
 * CommandBar, modals) never re-render when global mood, lookTarget, or pointer
 * coordinates update. Pointer coordinates travel via ref + listener subscription
 * with zero React re-renders.
 */
export function FaceProvider({
  children,
  trackPointer = true,
  config = ACTIVE_FACE_CONFIG,
  doneDurationMs,
}: FaceProviderProps) {
  const effectiveDoneMs = doneDurationMs ?? config.motion.doneDurationMs;
  const entriesRef = useRef<Map<string, FaceActivityEntry>>(new Map());
  const modalSlotsRef = useRef<Set<string>>(new Set());
  const seqRef = useRef(0);
  const doneTimersRef = useRef<Record<FaceScope, number | null>>({
    global: null,
    modal: null,
  });
  const pointerRef = useRef<FacePoint | null>(null);
  const pointerListenersRef = useRef<Set<(point: FacePoint | null) => void>>(new Set());

  const [revision, setRevision] = useState(0);
  const [hasModalSlot, setHasModalSlot] = useState(false);
  const [lookTarget, setLookTargetState] = useState<FacePoint | null>(null);

  const bump = useCallback(() => {
    setRevision((n) => n + 1);
  }, []);

  const setActivity = useCallback(
    (entry: Omit<FaceActivityEntry, 'updatedAt'>) => {
      const next: FaceActivityEntry = {
        ...entry,
        updatedAt: ++seqRef.current,
      };
      entriesRef.current.set(entry.id, next);
      bump();
    },
    [bump],
  );

  const removeActivity = useCallback(
    (id: string) => {
      if (entriesRef.current.delete(id)) {
        bump();
      }
    },
    [bump],
  );

  const notifyDone = useCallback(
    (label?: string, scope: FaceScope = 'global') => {
      const existingTimer = doneTimersRef.current[scope];
      if (existingTimer !== null) {
        window.clearTimeout(existingTimer);
        doneTimersRef.current[scope] = null;
      }
      const doneId = `__face_done_pulse_${scope}__`;
      entriesRef.current.set(doneId, {
        id: doneId,
        mood: 'done',
        label,
        scope,
        updatedAt: ++seqRef.current,
      });
      bump();
      doneTimersRef.current[scope] = window.setTimeout(() => {
        doneTimersRef.current[scope] = null;
        if (entriesRef.current.delete(doneId)) {
          bump();
        }
      }, effectiveDoneMs);
    },
    [bump, effectiveDoneMs],
  );

  useEffect(() => {
    return () => {
      if (doneTimersRef.current.global !== null) {
        window.clearTimeout(doneTimersRef.current.global);
      }
      if (doneTimersRef.current.modal !== null) {
        window.clearTimeout(doneTimersRef.current.modal);
      }
    };
  }, []);

  const registerModalSlot = useCallback((id: string) => {
    modalSlotsRef.current.add(id);
    setHasModalSlot(modalSlotsRef.current.size > 0);
  }, []);

  const unregisterModalSlot = useCallback((id: string) => {
    modalSlotsRef.current.delete(id);
    setHasModalSlot(modalSlotsRef.current.size > 0);
  }, []);

  const setLookTarget = useCallback((next: FacePoint | null) => {
    setLookTargetState((prev) => {
      if (prev === next) return prev;
      if (prev && next && prev.x === next.x && prev.y === next.y) return prev;
      return next;
    });
  }, []);

  const subscribePointer = useCallback(
    (listener: (point: FacePoint | null) => void) => {
      pointerListenersRef.current.add(listener);
      listener(pointerRef.current);
      return () => {
        pointerListenersRef.current.delete(listener);
      };
    },
    [],
  );

  useEffect(() => {
    if (!trackPointer || typeof window === 'undefined') return undefined;
    /** Forward viewport pointer coordinates to subscribed faces without React state updates. */
    const emitPointer = (point: FacePoint | null) => {
      pointerRef.current = point;
      for (const listener of pointerListenersRef.current) {
        listener(point);
      }
    };
    /** Update pointer coordinates on move. */
    const onPointerMove = (event: PointerEvent) => {
      emitPointer({ x: event.clientX, y: event.clientY });
    };
    /** Clear pointer gaze when the pointer leaves the document. */
    const onMouseLeave = () => {
      emitPointer(null);
    };
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    document.addEventListener('mouseleave', onMouseLeave);
    return () => {
      window.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('mouseleave', onMouseLeave);
    };
  }, [trackPointer]);

  const resolved = useMemo<ResolvedFaceState>(() => {
    void revision;
    const scope: FaceScope = hasModalSlot ? 'modal' : 'global';
    const active = resolveForScope(entriesRef.current, scope);
    return {
      mood: active.mood,
      label: active.label,
      stepIndex: active.stepIndex,
      hasModalSlot,
      lookTarget,
      config,
    };
  }, [revision, hasModalSlot, lookTarget, config]);

  const actions = useMemo<FaceActionsValue>(
    () => ({
      setActivity,
      removeActivity,
      notifyDone,
      registerModalSlot,
      unregisterModalSlot,
      setLookTarget,
      subscribePointer,
    }),
    [
      setActivity,
      removeActivity,
      notifyDone,
      registerModalSlot,
      unregisterModalSlot,
      setLookTarget,
      subscribePointer,
    ],
  );

  return (
    <FaceActionsContext.Provider value={actions}>
      <FaceStateContext.Provider value={resolved}>{children}</FaceStateContext.Provider>
    </FaceActionsContext.Provider>
  );
}

/**
 * Read the identity-stable action callbacks (null when outside FaceProvider).
 */
export function useFaceActions(): FaceActionsValue | null {
  return useContext(FaceActionsContext);
}

/**
 * Read the resolved face state (null when outside FaceProvider).
 */
export function useFaceState(): ResolvedFaceState | null {
  return useContext(FaceStateContext);
}

/**
 * Read the combined FaceContext (null when rendered outside FaceProvider).
 */
export function useFaceContext(): FaceContextValue | null {
  const state = useContext(FaceStateContext);
  const actions = useContext(FaceActionsContext);
  return useMemo(() => {
    if (!state || !actions) return null;
    return { state, ...actions };
  }, [state, actions]);
}
