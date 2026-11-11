// The full-bleed page backdrop: a static cyan to violet wash, a faint
// dot grid, and the vendored Aurora flowing across the top. It sits
// behind every app state (loading, session expired, dashboard).
//
// It is mounted OUTSIDE React.StrictMode on purpose (see main.tsx). The
// vendored Aurora releases its WebGL context on cleanup, which is right
// for a real unmount; StrictMode's development-only simulated remount
// reuses the same canvas, so the second mount would inherit a dead
// context and the canvas would composite as a flat gray sheet.
//
// If the context is ever lost for real (a GPU reset, a driver update),
// the Aurora is dropped and the static wash alone carries the page,
// which is also what shows when WebGL2 is not available at all.
import { useEffect, useRef, useState } from 'react';
import Aurora from '../vendor/reactbits/Aurora';

const AURORA_STOPS = ['#22D3EE', '#8B5CF6', '#22C55E'];

export default function Backdrop() {
  const hostRef = useRef<HTMLDivElement>(null);
  const [alive, setAlive] = useState(true);

  useEffect(() => {
    const canvas = hostRef.current?.querySelector('canvas');
    if (!canvas) return undefined;
    const onLost = () => setAlive(false);
    canvas.addEventListener('webglcontextlost', onLost);
    return () => canvas.removeEventListener('webglcontextlost', onLost);
  }, []);

  return (
    <div className="backdrop" aria-hidden="true">
      <div className="backdrop-grid" />
      <div className="backdrop-aurora" ref={hostRef}>
        {alive ? (
          <Aurora
            colorStops={AURORA_STOPS}
            amplitude={1.1}
            blend={0.72}
            speed={0.6}
            height={0.4}
            glow={0.6}
            opacity={0.62}
          />
        ) : null}
      </div>
    </div>
  );
}
