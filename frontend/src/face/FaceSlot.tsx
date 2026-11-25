import { useEffect, useId } from 'react';
import AgentFace from './AgentFace';
import type { FaceConfig } from './config';
import { useFaceActions, useFaceState } from './FaceProvider';

/** Props for FaceSlot. */
export interface FaceSlotProps {
  /** Which shell region hosts this slot. */
  slot: 'rail' | 'modal';
  /** Size variant ('md' default 32px, 'sm' 24px). */
  size?: 'md' | 'sm';
  /** Optional config override forwarded to AgentFace. */
  config?: FaceConfig;
  /** Optional className forwarded to AgentFace. */
  className?: string;
}

/**
 * Mount point for the agent face in either the navigation rail or a modal header.
 *
 * When a modal slot is mounted, the rail slot hides automatically so only one
 * face is visible and only the modal's activity drives it. Safe when rendered
 * outside FaceProvider (renders a calm idle face for rail).
 */
export default function FaceSlot({ slot, size = 'md', config, className }: FaceSlotProps) {
  const slotId = useId();
  const state = useFaceState();
  const actions = useFaceActions();
  const registerModal = actions?.registerModalSlot;
  const unregisterModal = actions?.unregisterModalSlot;

  useEffect(() => {
    if (slot !== 'modal' || !registerModal || !unregisterModal) return undefined;
    registerModal(slotId);
    return () => unregisterModal(slotId);
  }, [slot, slotId, registerModal, unregisterModal]);

  if (slot === 'rail' && state?.hasModalSlot) {
    return null;
  }

  const mood = state?.mood ?? 'idle';
  const label = state?.label;
  const stepIndex = state?.stepIndex;
  const lookTarget = state?.lookTarget ?? null;

  return (
    <span className={`face-slot face-slot-${slot}`} data-face-slot={slot}>
      <AgentFace
        size={size}
        mood={mood}
        label={label}
        stepIndex={stepIndex}
        lookTarget={lookTarget}
        subscribePointer={actions?.subscribePointer}
        config={config ?? state?.config}
        className={className}
      />
    </span>
  );
}
