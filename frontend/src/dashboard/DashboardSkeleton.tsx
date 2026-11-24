// The dashboard's first load (spec 027, F2): the shell and the brief's
// own geometry in dotted wire, not a centered text card, so the page
// does not rearrange when the payload lands. Nothing shows under 100 ms;
// after ten seconds the one phase line says the wait is longer than
// usual.
import Rail from './Rail';
import { PhaseText, usePhase } from '../components/feedback';
import { WireChart } from './cells';

/** Dotted text lines of the given widths. */
function WireLines({ widths }: { widths: number[] }) {
  return (
    <div className="wire-lines" aria-hidden="true">
      {widths.map((width, index) => <span key={index} style={{ width: `${width}%` }} />)}
    </div>
  );
}

/**
 * The loading shell: the rail, the hero's greeting box, the command bar
 * and the brief's columns and cells, all in the app's own layout.
 */
export default function DashboardSkeleton() {
  const load = usePhase(true, 'dashboard-load');
  if (!load.shown) return null;
  return (
    <div className="app">
      <a className="skip-link" href="#dashboard-main">Skip to main content</a>
      <Rail inboxWaiting={0} />
      <main id="dashboard-main" tabIndex={-1} aria-busy="true">
        <header className="hero">
          <div>
            <div className="skeleton-title" aria-hidden="true" />
            <div className="wire-lines hero-meta-wire" aria-hidden="true">
              <span style={{ width: '220px' }} />
              <span style={{ width: '140px' }} />
            </div>
          </div>
          <div className="hero-actions">
            <div className="skeleton-btn" aria-hidden="true" />
          </div>
        </header>
        <p className="phase-line" role="status" aria-busy="true">
          <span className="btn-busy-dot" aria-hidden="true" />
          <span><PhaseText text="Reading the dashboard…" slow={load.slow} /></span>
        </p>
        <div className="cmd skeleton-cmd" aria-hidden="true">
          <div className="cmd-inner">
            <div className="wire-lines" style={{ flex: '1 1 220px' }}>
              <span style={{ width: '78%' }} />
              <span style={{ width: '48%' }} />
            </div>
            <div className="skeleton-btn" />
          </div>
        </div>
        <div className="brief" aria-hidden="true">
          <div className="brief-col brief-main">
            <div className="cell cell-hero skeleton-cell">
              <WireLines widths={[28, 44]} />
              <WireChart />
            </div>
            <div className="cell cell-moves skeleton-cell">
              <WireLines widths={[22, 40, 34]} />
              <div className="wire-rows"><span /><span /><span /><span /></div>
            </div>
          </div>
          <div className="brief-col brief-side">
            <div className="cell cell-decisions skeleton-cell">
              <WireLines widths={[40, 86, 70]} />
            </div>
            <div className="cell cell-digest skeleton-cell">
              <WireLines widths={[36, 80, 62]} />
            </div>
          </div>
          {[0, 1, 2].map((index) => (
            <div className="cell span-4 skeleton-cell" key={index}>
              <WireLines widths={[32, 76, 58]} />
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
