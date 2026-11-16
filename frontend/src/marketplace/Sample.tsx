// The live sample preview. It renders the server's rendered sample payload
// through the same WidgetCard surface the dashboard uses, so a plugin that
// looks wrong here looks wrong installed.
import type { ReactNode } from 'react';
import WidgetCard from '../components/WidgetCard';
import type { MarketElement, MarketSample } from './types';

function display(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
  }
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function missingText(state: string | undefined, reason: string | undefined, fallback: string): string {
  const stateText = state?.trim() || fallback;
  const reasonText = reason?.trim();
  return reasonText ? `${stateText}. ${reasonText}` : stateText;
}

function Missing({ element, fallback }: { element: MarketElement; fallback: string }) {
  return (
    <span className="mkt-sample-missing">
      {missingText(element.state, element.reason, fallback)}
    </span>
  );
}

function Sparkline({ points, label, element }: { points: number[]; label: string; element: MarketElement }) {
  const values = points.filter((p) => Number.isFinite(p));
  if (values.length < 2) {
    return (
      <p className="mkt-sample-empty">
        {label}: {missingText(element.state, element.reason, 'no points reported')}
      </p>
    );
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const coords = values.map((value, i) => {
    const x = (i / (values.length - 1)) * 100;
    const y = 30 - ((value - min) / span) * 26 - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <figure className="mkt-spark">
      <svg viewBox="0 0 100 30" preserveAspectRatio="none" role="img"
           aria-label={`${label}: ${values.length} points, low ${display(min)}, high ${display(max)}`}>
        <polyline points={coords} fill="none" stroke="currentColor" strokeWidth="1.6"
                  vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption>
        <span>{label}</span>
        <span className="mkt-mono">{display(values[values.length - 1])} now</span>
      </figcaption>
    </figure>
  );
}

export function SampleElement({ element }: { element: MarketElement }) {
  const kind = element.kind || 'text';
  switch (kind) {
    case 'metric': {
      const value = display(element.value);
      return (
        <div className="mkt-sample-metric">
          {value
            ? <span className="w-big mkt-mono">{value}</span>
            : <Missing element={element} fallback="No value reported" />}
          <span className="w-note">{element.label}</span>
        </div>
      );
    }
    case 'delta': {
      const value = display(element.value);
      return (
        <div className={`mkt-sample-delta mkt-tone-${element.tone || 'neutral'}`}>
          {value ? (
            <>
              <span className="mkt-mono">{value}</span>
              <span>{element.direction === 'down' ? 'Down' : element.direction === 'up' ? 'Up' : element.direction === 'flat' ? 'Flat' : ''}</span>
            </>
          ) : (
            <Missing element={element} fallback="No change reported" />
          )}
          <span className="w-note">{element.label}{element.window ? ` · ${element.window}` : ''}</span>
        </div>
      );
    }
    case 'progress': {
      const value = typeof element.value === 'number' && Number.isFinite(element.value)
        ? element.value : null;
      const target = typeof element.target === 'number' && Number.isFinite(element.target)
        ? element.target : null;
      const usable = value !== null && target !== null && target > 0;
      const pct = usable ? Math.max(0, Math.min(100, (value / target) * 100)) : 0;
      return (
        <div className="mkt-sample-progress">
          <div className="mkt-sample-row">
            <span>{element.label}</span>
            {usable ? (
              <span className="mkt-mono">{display(value)}{element.unit || ''} / {display(target)}{element.unit || ''}</span>
            ) : (
              <Missing
                element={element}
                fallback={value === null ? 'Progress not reported' : 'Target not reported'}
              />
            )}
          </div>
          {usable && (
            <div className="mkt-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100}
                 aria-valuenow={Math.round(pct)} aria-label={element.label || 'Progress'}>
              <span style={{ width: `${pct}%` }} />
            </div>
          )}
        </div>
      );
    }
    case 'list': {
      const rows = element.rows ?? [];
      return (
        <div className="mkt-sample-block">
          {element.title && <h3 className="mkt-sample-title">{element.title}</h3>}
          {rows.length === 0 ? (
            <Missing element={element} fallback="No rows reported" />
          ) : (
            <ul className="mkt-sample-list">
              {rows.map((row, i) => (
                <li key={i}>
                  <span>{display(row.primary)}</span>
                  {row.secondary && <span className="w-note">{display(row.secondary)}</span>}
                  {row.meta && <span className="mkt-mono w-note">{display(row.meta)}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      );
    }
    case 'table': {
      const rows = element.rows ?? [];
      const columns = element.columns ?? [];
      return (
        <div className="mkt-sample-block mkt-table-wrap">
          {element.title && <h3 className="mkt-sample-title">{element.title}</h3>}
          {rows.length === 0 || columns.length === 0 ? (
            <Missing element={element} fallback="No table rows reported" />
          ) : (
            <table className="rows">
              <thead>
                <tr>{columns.map((c, i) => <th key={i} scope="col">{c}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i}>
                    <td>{display(row.primary)}</td>
                    <td>{display(row.secondary)}</td>
                    <td>{display(row.meta)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      );
    }
    case 'sparkline':
      return <Sparkline points={element.points ?? []} label={element.label || 'Trend'} element={element} />;
    case 'status': {
      const value = display(element.value);
      return (
        <p className={`mkt-sample-status mkt-tone-${element.tone || 'neutral'}`}>
          <span className="mkt-dot" aria-hidden="true" />
          <strong>{value || <Missing element={element} fallback="No status reported" />}</strong>
          <span>{element.label}</span>
        </p>
      );
    }
    case 'timeline': {
      const items = element.items ?? [];
      return (
        <div className="mkt-sample-block">
          {element.title && <h3 className="mkt-sample-title">{element.title}</h3>}
          {items.length === 0 ? (
            <Missing element={element} fallback="No events reported" />
          ) : (
            <ol className="mkt-sample-timeline">
              {items.map((item, i) => (
                <li key={i}>
                  <span className="mkt-mono w-note">{display(item.time)}</span>
                  <span>{display(item.title)}</span>
                  {item.meta && <span className="w-note">{display(item.meta)}</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      );
    }
    case 'checklist': {
      const items = element.items ?? [];
      return (
        <div className="mkt-sample-block">
          {element.title && <h3 className="mkt-sample-title">{element.title}</h3>}
          {items.length === 0 ? (
            <Missing element={element} fallback="No items reported" />
          ) : (
            <ul className="mkt-sample-checklist">
              {items.map((item, i) => (
                <li key={i} className={item.done ? 'is-done' : ''}>
                  <span className="mkt-check" aria-hidden="true">{item.done ? '✓' : ''}</span>
                  <span>{display(item.text)}</span>
                  <span className="w-note">{item.done ? 'Done' : 'Open'}{item.due ? ` · due ${display(item.due)}` : ''}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      );
    }
    case 'text': {
      const text = display(element.text ?? element.value);
      return text ? (
        <p className="mkt-sample-text">{text}</p>
      ) : (
        <p className="mkt-sample-text"><Missing element={element} fallback="No text reported" /></p>
      );
    }
    default: {
      const text = display(element.text ?? element.value);
      return (
        <p className="mkt-sample-text">
          {element.label ? `${element.label}: ` : ''}
          {text || <Missing element={element} fallback="No value reported" />}
        </p>
      );
    }
  }
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="mkt-sample-grid">{children}</div>;
}

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
        <Grid>
          {sample.elements.map((element, i) => (
            <SampleElement key={i} element={element} />
          ))}
        </Grid>
      </WidgetCard>
    </div>
  );
}
