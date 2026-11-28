// The shape GET /api/memory/graph answers (src/nexuusbot/server/
// memory_graph_api.py). Every node is a real row in the memory store or
// the action that wrote one; nothing here is invented client-side.

export type NodeKind = 'origin' | 'source' | 'fact' | 'entity' | 'observation';
export type EdgeType = 'wrote' | 'extracted' | 'mentions' | 'cites' | 'temporal' | 'semantic';
export type StepId = 'retain' | 'extract' | 'approve' | 'store' | 'link' | 'reflect';

export interface ProvenanceStep {
  step: StepId;
  ts: number | null;
  text: string;
}

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  text: string;
  steps: ProvenanceStep[];
  sample?: boolean;
  createdTs?: number;
  occurredTs?: number | null;
  updatedTs?: number;
  factKind?: 'world' | 'experience';
  entityType?: string;
  aliases?: string[];
  factCount?: number;
  confidence?: number;
  speaker?: string;
  origin?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: EdgeType;
  weight?: number;
}

export interface PipelineStep {
  step: StepId;
  count: number;
  text: string;
  waiting?: number;
}

export interface MemoryGraphData {
  status: 'ok';
  semantic: boolean;
  truncated: boolean;
  pipeline: PipelineStep[];
  nodes: GraphNode[];
  edges: GraphEdge[];
}
