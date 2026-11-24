// The marketplace JSON DTOs, mirroring src/agentdesk/marketplace/catalog.py
// and api.py exactly. Field names keep the server's spelling.

import type { PluginElement } from '../types';

export interface IneligibleReason {
  code: string;
  message: string;
}

export interface MarketCard {
  id: string;
  name: string;
  version: string;
  publisher: string;
  publisherVerified: boolean;
  category: string;
  tags: string[];
  summary: string;
  icon: string;
  riskTier: string;
  source: string;
  eligible: boolean;
  ineligibleReasons: IneligibleReason[];
  deprecated: { reason?: string; advisory?: string; replacement?: string | null } | null;
  yanked: boolean;
  sampleAvailable: boolean;
}

export interface MarketSignature {
  status: string;
  keyId: string;
  fingerprint: string;
  signedAt: string;
}

export interface MarketCapabilities {
  sources: string[];
  permissions: string[];
  elementKinds: string[];
  filesystem: string[];
  network: string[];
}

export interface MarketValidation {
  checkedAt: string;
  ok: boolean | null;
  failures: { code: string; message: string }[];
}

export interface MarketDetail extends MarketCard {
  description: string;
  highlights: string[];
  license: string;
  homepage: string;
  requires: Record<string, unknown>;
  minHost: string;
  digest: string;
  signature: MarketSignature;
  provenance: { builder?: string; sourceCommit?: string };
  capabilities: MarketCapabilities;
  changelog: { version?: string; text?: string; date?: string };
  publishedAt: string;
  validation: MarketValidation;
}

export interface InstalledSummary {
  id: string;
  name: string;
  version: string;
  pinned: { version: string; sha256: string };
  status: { status: string; cause: string; checked_at: string };
  pilot: { views: number; remaining: number };
  update: {
    version: string;
    digest: string;
    widening: string[];
    scopes: string[];
  } | null;
  pendingConsent: boolean;
  shared: boolean;
  enabled: boolean;
  dataDirSize: number;
}

export interface MarketPolicy {
  mode: string;
  source: string;
  signatureStatus: string;
}

export interface CatalogResponse {
  entries: MarketCard[];
  total: number;
  sources: { source: string; count: number }[];
  policy: MarketPolicy;
  // True only when the plugin runner carries an HTTP transport. Absent on
  // older servers, which must not be read as false.
  deskNetwork?: boolean;
}

export interface MarketVersion {
  version: string;
  digest: string;
  yanked: boolean;
}

export interface MarketSample {
  elements: MarketElement[];
  status: string;
  cause: string;
  checked_at: string;
}

export interface DetailResponse {
  plugin: MarketDetail;
  installed: InstalledSummary | null;
  versions: MarketVersion[];
  alternatives: MarketCard[];
  sample: MarketSample | null;
  deskNetwork?: boolean;
}

export interface InstalledResponse {
  plugins: InstalledSummary[];
  policy: MarketPolicy;
  deskNetwork?: boolean;
}

// -- per-instance setup (T5) ----------------------------------------------

// The instance document the plugin runtime stores per configured instance
// (agentdesk.plugins.config). The manage view reads it through
// GET /api/plugins/<id>/instances.
export interface InstanceDocument {
  schemaVersion?: number;
  instanceId: string;
  name: string;
  source: {
    kind?: string;
    path?: string | null;
    sheet?: string | null;
    headerRow?: number | null;
    range?: string | null;
  } | null;
  tracking?: Record<string, unknown>;
  confirmedAt: string | null;
  suggested?: boolean;
}

export interface InstancesResponse {
  pluginId: string;
  configBacked: boolean;
  aliasOf: string | null;
  // The plugin id whose setup endpoints this surface drives: an alias
  // answers its target, so the alias never opens a second config surface.
  setupPluginId: string;
  setupPluginName: string;
  instances: InstanceDocument[];
}

export interface PublisherResponse {
  publisher: string;
  verified: boolean;
  proof: unknown;
  plugins: MarketCard[];
  firstSeen: string;
  deskNetwork?: boolean;
}

// Every slot DTO the host renderer can emit. The detail sample draws
// these, so the preview is the real renderer, not a mock of one.
export interface MarketElement {
  kind: string;
  label?: string;
  value?: string | number;
  text?: string;
  direction?: string;
  window?: string;
  tone?: string;
  unit?: string;
  target?: number | null;
  title?: string;
  rows?: {
    primary?: string;
    secondary?: string;
    meta?: string;
  }[];
  columns?: string[];
  points?: number[];
  min?: number | null;
  max?: number | null;
  items?: {
    time?: string;
    title?: string;
    meta?: string;
    text?: string;
    done?: boolean;
    due?: string;
  }[];
  state?: string;
  reason?: string;
}

/**
 * Adapt one marketplace sample element to the dashboard's element shape.
 *
 * The server renders samples with the same ten kinds the dashboard draws, so
 * this is only the structural widening the two DTOs need: the kind is
 * narrowed to the known union and the sample-only fields are left behind.
 */
export function toPluginElement(element: MarketElement): PluginElement {
  return {
    kind: element.kind as PluginElement['kind'],
    label: element.label,
    title: element.title,
    value: element.value,
    text: element.text,
    direction: element.direction,
    points: element.points,
    rows: element.rows,
    columns: element.columns,
    items: element.items,
    target: element.target,
    unit: element.unit,
    tone: element.tone as PluginElement['tone'],
    reason: element.reason,
  };
}

export interface PackMember {
  id: string;
  name: string;
  version: string;
  eligible: boolean;
  ineligibleReasons: IneligibleReason[];
  scopes: string[];
}

export interface Pack {
  id: string;
  name: string;
  audience: string;
  summary: string;
  icon: string;
  excluded: { id: string; reason: string }[];
  sampleData: boolean;
  firstRun: boolean;
  plugins: MarketCard[];
  members: PackMember[];
  eligible: boolean;
  blockedMember: string | null;
  blockedReason: string;
}

export interface PacksResponse {
  packs: Pack[];
  total: number;
  policy: MarketPolicy;
}

// -- enterprise policy, admin and trust center (T13) ---------------------

export interface MarketAnchor {
  epoch: number;
  fingerprints: string[];
}

export interface MarketPolicyVerification {
  signatureStatus: string;
  warning: string | null;
  epoch: number;
  signerFingerprint: string | null;
  expiresAt: string | null;
}

export interface AdminPosture {
  mode: string;
  riskCeiling: string;
  requireSignatures: boolean;
  killSwitch: string[];
  allowedPublishers: string[];
  allowedCategories: string[];
  networkAllowlist: string[];
  enabledSources: string[];
}

export interface PendingPublication {
  id: string;
  pluginId: string;
  version: string;
  publisher: string;
  submittedAt: string;
  changelog: string;
}

export interface RevokedEntry {
  id: string;
  version: string;
  action: string;
  reason: string;
  at: string;
  epoch: number;
}

export interface InventoryItem {
  id: string;
  version: string;
  publisher: string;
  digest: string;
  enabled: boolean;
  eligible: boolean;
  reasons?: IneligibleReason[];
}

export interface AdminSnapshot {
  posture: AdminPosture;
  anchor: MarketAnchor;
  policy: MarketPolicyVerification;
  pending: PendingPublication[];
  revoked: RevokedEntry[];
  inventory: InventoryItem[];
  catalogSource: string;
  auditEvents: number;
}

export interface PolicyDiffEntry {
  field: string;
  before: unknown;
  after: unknown;
}

export interface PolicyImportResult {
  diff: PolicyDiffEntry[];
  verification: MarketPolicyVerification;
  applied: boolean;
}

export interface ValidatorRun {
  at: string | null;
  ok: boolean | null;
  failures: IneligibleReason[];
  scope: string | null;
}

export interface TrustSnapshot {
  anchor: MarketAnchor;
  policy: MarketPolicy & {
    warning?: string | null;
    epoch?: number;
    signerFingerprint?: string | null;
    expiresAt?: string | null;
  };
  lastValidatorRun: ValidatorRun;
  guarantees: string[];
  cannotHappen: string[];
  reportPath: string;
}

