// The live sample preview. It renders the server's rendered sample payload
// through the same WidgetCard surface and the same ElementView the dashboard
// uses, so a plugin that looks wrong here looks wrong installed.
import WidgetCard from '../components/WidgetCard';
import { ElementView } from '../dashboard/PluginCardView';
import { toPluginElement, type MarketSample } from './types';

/**
 * Render one plugin's bundled sample as the dashboard would draw it.
 *
 * A plugin without a sample keeps the honest empty note; a sample the host
 * flagged keeps its stale cause. The elements themselves go through the
 * dashboard's ElementView, so the preview cannot grow a second renderer or
 * a second vocabulary beside the installed card's.
 */
export function SamplePreview({ sample, title }: { sample: MarketSample | null; title: string }) {
  if (!sample) {
    return (
      <p className="mkt-empty-inline">
        This plugin ships no sample, so there is nothing to preview yet.
      </p>
    );
  }
  const stale = sample.status !== 'fresh';
  return (
    <div className="mkt-sample-wrap">
      <div className="mkt-sample-heading">
        <h2>Live sample</h2>
        <span className="mkt-chip mkt-chip-sample">Sample data</span>
      </div>
      <p className="mkt-sample-note">
        Rendered from the plugin's bundled sample. No live data was read.
        {stale && sample.cause ? ` ${sample.cause}` : ''}
      </p>
      <WidgetCard
        title={title}
        span="span-12"
        stamp={{ fresh: !stale, text: stale ? 'Sample needs attention' : 'Sample data' }}
        amber={stale}
        foot={(<span>Sample checked {sample.checked_at || 'at build time'}</span>)}
      >
        <div className="mkt-sample-grid">
          {sample.elements.map((element, i) => (
            <ElementView key={i} element={toPluginElement(element)} />
          ))}
        </div>
      </WidgetCard>
    </div>
  );
}
