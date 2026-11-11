// One installed plugin's dashboard card, rendered from the payload's
// plugin data (never server HTML). Fresh: the version and what it is
// reading. Attention: the cause and the honest note about Re-test, amber.
import type { PluginCard } from '../types';
import WidgetCard from '../components/WidgetCard';

interface PluginCardViewProps {
  card: PluginCard;
}

export default function PluginCardView({ card }: PluginCardViewProps) {
  const fresh = card.freshness === 'fresh';
  return (
    <WidgetCard
      title={card.title}
      span="span-4"
      badge={card.pilot ? 'PILOT' : undefined}
      stamp={fresh ? { fresh: true, text: 'live' } : { fresh: false, text: 'Re-test available' }}
      amber={!fresh}
      foot={`plugin v${card.version}`}
    >
      {fresh ? (
        <>
          <p className="w-big">{card.version}</p>
          <p className="w-note">reading the data source</p>
        </>
      ) : (
        <div className="alert" role="status">
          <p>{card.cause || 'data source has not run'}</p>
          <p>
            Re-test runs the plugin's data source again; the nightly probe
            does the same for every plugin.
          </p>
        </div>
      )}
    </WidgetCard>
  );
}
