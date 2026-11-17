// The shape GET /api/memory/loop answers (src/agentdesk/server/
// memory_loop_api.py). Every row is a stored fact, entity, excerpt,
// observation or a waiting review card; nothing is invented here.

export interface ChannelSetting {
  id: string;
  label: string;
  setting: string;
  on: boolean;
}

export interface CaptureState {
  enabled: boolean;
  autoApprove: boolean;
  channels: ChannelSetting[];
}

export interface Excerpt {
  id: number;
  text: string;
  speaker: string;
  createdTs: number;
}

export interface Candidate {
  cardId: string;
  type: 'fact' | 'observation';
  text: string;
  title: string;
  createdTs: number;
  channel: string;
  channelLabel: string;
  method: 'model' | 'rules' | string;
  entities: { name: string; type: string }[];
  excerpt: Excerpt | null;
  kind?: string;
  confidence?: number;
  cites?: { id: number; text: string }[];
}

export interface FactRow {
  id: number;
  text: string;
  kind: string;
  createdTs: number;
  occurredTs: number | null;
  origin: { id: string; label: string; how: string };
  sample: boolean;
  sourceId: number | null;
  excerpt: Excerpt | null;
  entities: { id: number; name: string }[];
  replacedBy: number | null;
  replaces: number[];
  observationIds: number[];
}

export interface EntityRow {
  id: number;
  name: string;
  type: string;
  aliases: string[];
  factCount: number;
}

export interface SourceRow {
  id: number;
  text: string;
  speaker: string;
  channel: string;
  channelLabel: string;
  createdTs: number;
  factIds: number[];
}

export interface ObservationRow {
  id: number;
  text: string;
  confidence: number;
  factIds: number[];
  createdTs: number;
  updatedTs: number;
  staleTs: number | null;
  entityId: number | null;
  derived: 'consolidated' | 'reflected';
}

export interface LastCapture {
  channel: string;
  channelLabel: string;
  method: string;
  cause: string;
  found: number;
  skipped: number;
  staged: number;
  stored: number;
  ts: number;
}

export interface LoopState {
  status: 'ok';
  capture: CaptureState;
  extractor: { mode: 'model' | 'rules'; detail: string };
  lastCapture: LastCapture | null;
  undoWindowS: number;
  counts: {
    waiting: number;
    facts: number;
    standing: number;
    replaced: number;
    entities: number;
    observations: number;
    flagged: number;
    sources: number;
  };
  candidates: Candidate[];
  facts: FactRow[];
  entities: EntityRow[];
  sources: SourceRow[];
  observations: ObservationRow[];
}

export type TargetType = 'fact' | 'source' | 'entity' | 'observation';

export interface RemovalPlan {
  target: { type: TargetType; id: number; label: string };
  facts: { id: number; text: string }[];
  observationsRemoved: { id: number; text: string }[];
  observationsUpdated: { id: number; text: string }[];
  observationsFlagged: { id: number; text: string }[];
  entitiesRemoved: { id: number; name: string }[];
  entitiesUpdated: { id: number; name: string }[];
  factsRestored: { id: number; text: string }[];
  sourcesRemoved: number[];
}

export interface RemovalDone {
  facts: number[];
  observationsRemoved: number[];
  observationsFlagged: number[];
  observationsUpdated: number[];
  entitiesRemoved: number[];
  sourcesRemoved: number[];
  factsRestored: number[];
}
