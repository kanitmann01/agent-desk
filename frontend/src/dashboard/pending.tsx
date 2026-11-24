// The shaped placeholder a region shows while its result is on the way
// (spec 027, F2): the same dotted wireframe language the Moves cell and
// the tracker sketch already use, plus the one phase line. The caller
// puts it inside the element that will receive the result, so the result
// replaces it in place and the page does not jump a second time.
import { PhaseText, usePhase } from '../components/feedback';
import { WireChart } from './cells';

const LINE_WIDTHS = [92, 76, 86, 58, 82];

/** The dotted text lines, or a dotted chart, and the phase line; no hooks. */
export function PendingBody({
  phase,
  slow,
  lines = 3,
  chart = false,
  className = '',
}: {
  phase: string;
  slow: boolean;
  lines?: number;
  chart?: boolean;
  className?: string;
}) {
  return (
    <div className={className ? `pending-shape ${className}` : 'pending-shape'}>
      {chart ? <WireChart /> : (
        <div className="wire-lines" aria-hidden="true">
          {Array.from({ length: lines }, (_, index) => (
            <span key={index} style={{ width: `${LINE_WIDTHS[index % LINE_WIDTHS.length]}%` }} />
          ))}
        </div>
      )}
      <p className="phase-line" role="status">
        <span className="btn-busy-dot" aria-hidden="true" />
        <span><PhaseText text={phase} slow={slow} /></span>
      </p>
    </div>
  );
}

/** A placeholder that owns its own 100 ms gate and ten-second timer. */
export default function PendingShape({
  active,
  phase,
  phaseKey = '',
  lines = 3,
  chart = false,
  className = '',
}: {
  active: boolean;
  phase: string;
  phaseKey?: string;
  lines?: number;
  chart?: boolean;
  className?: string;
}) {
  const { shown, slow } = usePhase(active, phaseKey || phase);
  if (!shown) return null;
  return <PendingBody phase={phase} slow={slow} lines={lines} chart={chart} className={className} />;
}
