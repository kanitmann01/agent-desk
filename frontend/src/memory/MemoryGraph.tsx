// The Memory page graph: how each knowledge point got into the desk.
//
// Reads GET /api/memory/graph (the store's real rows) and draws them in
// the order agent-desk makes a point: where it came from, the fact, the
// observations reflected from facts, the entities facts link to. Above
// the picture, the pipeline strip counts each step of that path across
// the whole bank; beside it, the provenance panel answers "how was this
// made" for the selected point, step by step, with the moments the store
// recorded.
//
// Keyboard: the picture is one tab stop. Arrow keys move between points
// (up and down a column, left and right across columns), Enter or Space
// selects, Escape clears. Below 560px the picture becomes a list.
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { getJson } from '../api';
import { Glyph, GlyphShape } from './Glyph';
import { STEP_GLYPH, STEP_LABEL, glyphFor, kindWord, relation, stepUnit, when } from './copy';
import { COLUMNS, GAP, PILL, fitLabel, layoutGraph, lineage, neighbourFor, type Layout, type Placed } from './layout';
import type { GraphEdge, GraphNode, MemoryGraphData } from './types';

const LIST_BREAKPOINT = 560;

type Load =
  | { state: 'loading' }
  | { state: 'ready'; data: MemoryGraphData }
  | { state: 'failed'; message: string };

export interface MemoryGraphProps {
  endpoint?: string;
  // 'page' sits on the Memory page; 'full' is the /memory/graph page.
  mode?: 'page' | 'full';
  // Tests pin the width; the page measures its own box.
  initialWidth?: number;
}

export default function MemoryGraph({ endpoint = '/api/memory/graph', mode = 'page', initialWidth }: MemoryGraphProps) {
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getJson(endpoint)
      .then((res) => {
        if (!live) return;
        if (res.ok) setLoad({ state: 'ready', data: res.data as MemoryGraphData });
        else if (res.status === 401) setLoad({ state: 'failed', message: 'Your session ended. Open the desk from its shortcut to get a fresh link.' });
        else {
          const error = (res.data as { error?: string }).error;
          setLoad({ state: 'failed', message: error ? `The graph could not be read: ${error}` : 'The graph could not be read.' });
        }
      })
      .catch(() => live && setLoad({ state: 'failed', message: 'The graph could not reach its own server.' }));
    return () => {
      live = false;
    };
  }, [endpoint]);

  if (load.state === 'loading') {
    return (
      <section className="mg" aria-busy="true" aria-label="Memory graph">
        <p className="mg-quiet" role="status">Reading memory…</p>
      </section>
    );
  }
  if (load.state === 'failed') {
    return (
      <section className="mg" aria-label="Memory graph">
        <p className="mg-quiet" role="alert">{load.message}</p>
      </section>
    );
  }
  return <Ready data={load.data} mode={mode} selected={selected} onSelect={setSelected} initialWidth={initialWidth} />;
}

function Ready({
  data,
  mode,
  selected,
  onSelect,
  initialWidth,
}: {
  data: MemoryGraphData;
  mode: 'page' | 'full';
  selected: string | null;
  onSelect: (id: string | null) => void;
  initialWidth?: number;
}) {
  const facts = data.nodes.filter((node) => node.kind === 'fact');
  const entities = data.nodes.filter((node) => node.kind === 'entity');
  const sources = data.nodes.filter((node) => node.kind === 'source');
  const empty = !data.nodes.some((node) => node.kind === 'fact' || node.kind === 'observation');
  const byId = useMemo(() => new Map(data.nodes.map((node) => [node.id, node])), [data.nodes]);
  const chosen = selected ? byId.get(selected) ?? null : null;

  return (
    <section className={`mg mg-${mode}`} aria-labelledby="mg-title">
      <header className="mg-head">
        <div>
          <h2 id="mg-title">How this memory was made</h2>
          <p className="mg-sub">
            {empty
              ? 'Nothing is remembered yet. Each step below counts as it happens.'
              : `${count(facts.length, 'fact')} from ${count(sources.length, 'retained excerpt')}, linked to ${count(entities.length, 'entity', 'entities')}. Select any point to trace it back.`}
          </p>
        </div>
        {mode === 'page' && !empty && <a className="mg-open" href="/memory/graph">Open full page</a>}
      </header>

      <ol className="mg-pipeline" aria-label="How a knowledge point is made">
        {data.pipeline.map((step, index) => (
          <li key={step.step} className="mg-step">
            <span className="mg-step-top">
              <span className="mg-step-index mono">{String(index + 1).padStart(2, '0')}</span>
              <Glyph kind={STEP_GLYPH[step.step]} />
              <span className="mg-step-name">{STEP_LABEL[step.step]}</span>
            </span>
            <span className="mg-step-count mono">{stepUnit(step.step, step.count, step.waiting)}</span>
            <span className="mg-step-text">{step.text}</span>
          </li>
        ))}
      </ol>

      {empty ? (
        <EmptyGraph />
      ) : (
        <Body data={data} selected={selected} onSelect={onSelect} mode={mode} initialWidth={initialWidth}
          detail={<Provenance node={chosen} data={data} byId={byId} onSelect={onSelect} />} />
      )}
      {data.truncated && (
        <p className="mg-quiet">Showing the newest points only. The full page takes a date window.</p>
      )}
    </section>
  );
}

function count(n: number, noun: string, plural = `${noun}s`): string {
  return `${n} ${n === 1 ? noun : plural}`;
}

function EmptyGraph() {
  return (
    <div className="mg-empty">
      <div className="mg-empty-ghost" aria-hidden="true">
        {COLUMNS.map((column) => (
          <div key={column.id} className="mg-empty-col" style={{ flexGrow: column.weight }}>
            <span className="mg-col-title">{column.title}</span>
            <span className="mg-ghost-pill" />
            <span className="mg-ghost-pill short" />
          </div>
        ))}
      </div>
      <div className="mg-empty-copy">
        <h3>No knowledge points yet</h3>
        <p>
          A point arrives three ways: type a fact below, save a conversation from the{' '}
          <a href="/assistant">Assistant</a> and accept the drafts it proposes in the{' '}
          <a href="/inbox">Inbox</a>, or turn on Sample data in <a href="/settings">Settings</a> to see a labelled example.
        </p>
      </div>
    </div>
  );
}

function useWidth(initial?: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(initial ?? 0);
  useEffect(() => {
    const element = ref.current;
    if (!element || initial) return;
    const measure = () => {
      const style = getComputedStyle(element);
      const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
      setWidth(Math.max(element.clientWidth - (Number.isFinite(padding) ? padding : 0), 0));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [initial]);
  return [ref, width] as const;
}

// The picture and the provenance panel side by side; below the list
// breakpoint the picture becomes a list and the panel opens under the
// selected row, where the reader's eye already is.
function Body({
  data,
  selected,
  onSelect,
  mode,
  initialWidth,
  detail,
}: {
  data: MemoryGraphData;
  selected: string | null;
  onSelect: (id: string | null) => void;
  mode: 'page' | 'full';
  initialWidth?: number;
  detail: ReactNode;
}) {
  const [ref, width] = useWidth(initialWidth);
  const list = width > 0 && width < LIST_BREAKPOINT;
  return (
    <div className={`mg-body${list ? ' is-list' : ''}`}>
      <div className="mg-canvas" ref={ref}>
        {width === 0 ? null : list ? (
          <GraphList data={data} selected={selected} onSelect={onSelect} detail={detail} />
        ) : (
          <GraphPicture data={data} width={width} selected={selected} onSelect={onSelect} mode={mode} />
        )}
      </div>
      {!list && detail}
    </div>
  );
}

function edgePath(a: Placed, b: Placed, edge: GraphEdge): string {
  if (edge.type === 'temporal' || edge.type === 'semantic') {
    const side = edge.type === 'temporal' ? a.x : a.x + a.width;
    const bulge = Math.min(GAP - 8, 10 + Math.abs(b.y - a.y) * 0.12) * (edge.type === 'temporal' ? -1 : 1);
    return `M${side} ${a.y}C${side + bulge} ${a.y} ${side + bulge} ${b.y} ${side} ${b.y}`;
  }
  const [left, right] = a.column <= b.column ? [a, b] : [b, a];
  const x1 = left.x + left.width;
  const x2 = right.x;
  const mid = (x2 - x1) / 2;
  return `M${x1} ${left.y}C${x1 + mid} ${left.y} ${x2 - mid} ${right.y} ${x2} ${right.y}`;
}

function GraphPicture({
  data,
  width,
  selected,
  onSelect,
  mode,
}: {
  data: MemoryGraphData;
  width: number;
  selected: string | null;
  onSelect: (id: string | null) => void;
  mode: 'page' | 'full';
}) {
  const layout: Layout = useMemo(() => layoutGraph(data.nodes, data.edges, width), [data, width]);
  const lit = useMemo(() => (selected ? lineage(selected, data.edges) : null), [selected, data.edges]);
  const [focusId, setFocusId] = useState<string | null>(null);
  const nodeRefs = useRef(new Map<string, SVGGElement>());
  const order = useMemo(
    () => [...layout.placed.values()].sort((a, b) => a.column - b.column || a.y - b.y),
    [layout],
  );
  const tabStop = focusId ?? selected ?? order[0]?.node.id ?? null;

  const move = useCallback((id: string | null) => {
    if (!id) return;
    setFocusId(id);
    nodeRefs.current.get(id)?.focus();
  }, []);

  function onKey(event: KeyboardEvent<SVGGElement>, id: string) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onSelect(selected === id ? null : id);
    } else if (event.key === 'Escape') {
      onSelect(null);
    } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown' || event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      move(neighbourFor(layout, id, event.key));
    }
  }

  return (
    <div className="mg-picture">
      <div className="mg-cols" aria-hidden="true">
        {layout.columns.map((entry) => (
          <span key={entry.column.id} className="mg-col-title" style={{ left: entry.x, width: entry.width }}>
            {entry.column.title}
          </span>
        ))}
      </div>
      <div className={`mg-scroll${mode === 'full' ? ' mg-scroll-full' : ''}`}>
        <svg
          className="mg-svg"
          width={width}
          height={layout.height}
          viewBox={`0 0 ${width} ${layout.height}`}
          role="group"
          aria-label={`Memory graph, ${layout.placed.size} points. Arrow keys move between points, Enter selects, Escape clears.`}
        >
          <g className="mg-edges">
            {data.edges.map((edge) => {
              const a = layout.placed.get(edge.source);
              const b = layout.placed.get(edge.target);
              if (!a || !b) return null;
              const on = lit ? lit.has(edge.source) && lit.has(edge.target) && (edge.source === selected || edge.target === selected || isProvenance(edge)) : false;
              const dim = lit && !on;
              return (
                <path
                  key={`${edge.type}:${edge.source}:${edge.target}`}
                  className={`mg-edge mg-edge-${edge.type}${on ? ' is-lit' : ''}${dim ? ' is-dim' : ''}`}
                  d={edgePath(a, b, edge)}
                />
              );
            })}
          </g>
          <g className="mg-nodes">
            {order.map((place) => {
              const { node } = place;
              const isSelected = node.id === selected;
              const dim = lit ? !lit.has(node.id) : false;
              return (
                <g
                  key={node.id}
                  ref={(el) => {
                    if (el) nodeRefs.current.set(node.id, el);
                    else nodeRefs.current.delete(node.id);
                  }}
                  className={`mg-node mg-node-${node.kind}${isSelected ? ' is-selected' : ''}${dim ? ' is-dim' : ''}`}
                  transform={`translate(${place.x} ${place.y - PILL / 2})`}
                  role="button"
                  tabIndex={node.id === tabStop ? 0 : -1}
                  aria-pressed={isSelected}
                  aria-label={`${kindWord(node)}: ${node.label}`}
                  data-node-id={node.id}
                  onClick={() => {
                    setFocusId(node.id);
                    onSelect(isSelected ? null : node.id);
                  }}
                  onFocus={() => setFocusId(node.id)}
                  onKeyDown={(event) => onKey(event, node.id)}
                >
                  <title>{node.text}</title>
                  <rect className="mg-pill" width={place.width} height={PILL} rx={6} />
                  <g transform={`translate(13 ${PILL / 2})`}>
                    <GlyphShape kind={glyphFor(node)} />
                  </g>
                  <text className="mg-label" x={25} y={PILL / 2 + 4}>
                    {fitLabel(node.label, place.width)}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
      <EdgeKey data={data} />
    </div>
  );
}

function isProvenance(edge: GraphEdge): boolean {
  return edge.type === 'wrote' || edge.type === 'extracted' || edge.type === 'mentions' || edge.type === 'cites';
}

function EdgeKey({ data }: { data: MemoryGraphData }) {
  const present = new Set(data.edges.map((edge) => edge.type));
  const rows: { type: GraphEdge['type']; label: string }[] = [
    { type: 'wrote', label: 'wrote' },
    { type: 'extracted', label: 'extracted from' },
    { type: 'mentions', label: 'mentions' },
    { type: 'cites', label: 'cites' },
    { type: 'temporal', label: 'next in time' },
    { type: 'semantic', label: 'similar meaning' },
  ];
  return (
    <ul className="mg-key" aria-label="Link types">
      {rows.filter((row) => present.has(row.type)).map((row) => (
        <li key={row.type}>
          <svg width="22" height="8" aria-hidden="true">
            <path className={`mg-edge mg-edge-${row.type} is-key`} d="M1 4H21" />
          </svg>
          {row.label}
        </li>
      ))}
      {!present.has('semantic') && (
        <li className="mg-key-note">
          {data.semantic
            ? 'Similar-meaning links appear once facts are embedded.'
            : 'Similar-meaning links need Semantic memory on in Settings.'}
        </li>
      )}
    </ul>
  );
}

function GraphList({
  data,
  selected,
  onSelect,
  detail,
}: {
  data: MemoryGraphData;
  selected: string | null;
  onSelect: (id: string | null) => void;
  detail: ReactNode;
}) {
  return (
    <div className="mg-list">
      {COLUMNS.map((column) => {
        const members = data.nodes.filter((node) => column.kinds.includes(node.kind));
        if (!members.length) return null;
        return (
          <section key={column.id} aria-label={column.title}>
            <h3 className="mg-col-title">{column.title}</h3>
            <ul>
              {members.map((node) => (
                <li key={node.id}>
                  <button
                    type="button"
                    className={`mg-row${node.id === selected ? ' is-selected' : ''}`}
                    aria-pressed={node.id === selected}
                    onClick={() => onSelect(node.id === selected ? null : node.id)}
                  >
                    <Glyph kind={glyphFor(node)} />
                    <span>{node.label}</span>
                  </button>
                  {node.id === selected && <div className="mg-inline-detail">{detail}</div>}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function Provenance({
  node,
  data,
  byId,
  onSelect,
}: {
  node: GraphNode | null;
  data: MemoryGraphData;
  byId: Map<string, GraphNode>;
  onSelect: (id: string | null) => void;
}) {
  if (!node) {
    return (
      <aside className="mg-detail" aria-label="Provenance">
        <p className="mg-eyebrow">Provenance</p>
        <h3 className="mg-detail-title">Select a point to see how it was made</h3>
        <ul className="mg-legend">
          <li><Glyph kind="origin" /><span><b>Writer.</b> The action that wrote it: the Memory page, an inbox card you accepted, a plugin, the sample seed.</span></li>
          <li><Glyph kind="source" /><span><b>Retained excerpt.</b> A conversation you chose to save; facts are extracted from it.</span></li>
          <li><Glyph kind="fact" /><span><b>Fact.</b> A world fact, or an experience <Glyph kind="experience" /> of yours, kept in time order.</span></li>
          <li><Glyph kind="observation" /><span><b>Observation.</b> What a reflect run concluded, citing its facts.</span></li>
          <li><Glyph kind="entity" /><span><b>Entity.</b> A person, company or thing facts mention; shared entities join facts.</span></li>
        </ul>
      </aside>
    );
  }

  const groups = new Map<string, GraphNode[]>();
  for (const edge of data.edges) {
    const outward = edge.source === node.id;
    if (!outward && edge.target !== node.id) continue;
    const other = byId.get(outward ? edge.target : edge.source);
    if (!other) continue;
    const label = relation(edge.type, outward);
    const list = groups.get(label) ?? [];
    if (!list.includes(other)) list.push(other);
    groups.set(label, list);
  }

  const meta: [string, string][] = [];
  if (node.kind === 'fact') {
    meta.push(['Told to the desk', when(node.createdTs)]);
    if (node.occurredTs) meta.push(['Happened', when(node.occurredTs)]);
  } else if (node.kind === 'source') {
    meta.push(['Saved', when(node.createdTs)]);
    if (node.speaker) meta.push(['Speaker', node.speaker]);
  } else if (node.kind === 'entity') {
    if (node.aliases?.length) meta.push(['Also called', node.aliases.join(', ')]);
    meta.push(['Mentioned in', count(node.factCount ?? 0, 'fact')]);
  } else if (node.kind === 'observation') {
    meta.push(['First concluded', when(node.createdTs)]);
    meta.push(['Last updated', when(node.updatedTs)]);
  } else if (node.kind === 'origin') {
    meta.push(['Wrote here', count(node.factCount ?? 0, 'fact')]);
  }

  return (
    <aside className="mg-detail" aria-label="Provenance" aria-live="polite">
      <p className="mg-eyebrow">
        <Glyph kind={glyphFor(node)} />
        {kindWord(node)}
        {node.sample && <span className="mg-sample">Sample</span>}
      </p>
      <p className={`mg-detail-text${node.kind === 'source' ? ' is-quote' : ''}`}>{node.text}</p>
      {meta.length > 0 && (
        <dl className="mg-meta">
          {meta.map(([term, value]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd className="mono">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {node.steps.length > 0 && (
        <>
          <h4 className="mg-detail-h">How it was made</h4>
          <ol className="mg-steps">
            {node.steps.map((step, index) => (
              <li key={`${step.step}-${index}`}>
                <span className="mg-steps-name">
                  <Glyph kind={STEP_GLYPH[step.step]} />
                  {STEP_LABEL[step.step]}
                  {step.ts !== null && <time className="mono">{when(step.ts)}</time>}
                </span>
                <span className="mg-steps-text">{step.text}</span>
              </li>
            ))}
          </ol>
        </>
      )}
      {groups.size > 0 && (
        <>
          <h4 className="mg-detail-h">Connected</h4>
          <dl className="mg-links">
            {[...groups.entries()].map(([label, members]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>
                  {members.slice(0, 6).map((other) => (
                    <button key={other.id} type="button" className="mg-chip" onClick={() => onSelect(other.id)}>
                      <Glyph kind={glyphFor(other)} />
                      <span>{other.kind === 'fact' || other.kind === 'source' || other.kind === 'observation' ? fitLabel(other.label, 260) : other.label}</span>
                    </button>
                  ))}
                  {members.length > 6 && <span className="mg-quiet">+{members.length - 6} more</span>}
                </dd>
              </div>
            ))}
          </dl>
        </>
      )}
      <button type="button" className="mg-clear" onClick={() => onSelect(null)}>Clear selection</button>
    </aside>
  );
}
