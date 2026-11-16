// Shared marketplace DTO fixtures for the surface tests. They mirror the
// server shapes from src/agentdesk/marketplace/catalog.py, so a component
// cannot pass by depending on a field the API does not send.
import type {
  CatalogResponse, DetailResponse, InstalledResponse, InstalledSummary,
  MarketCard, MarketDetail, MarketSample, Pack, PacksResponse,
} from '../marketplace/types';

export function card(overrides: Partial<MarketCard> = {}): MarketCard {
  return {
    id: 'ar-aging',
    name: 'AR Aging',
    version: '1.2.0',
    publisher: 'agent-desk',
    publisherVerified: true,
    category: 'finance',
    tags: ['receivables', 'aging'],
    summary: 'Overdue invoices by customer, refreshed from the workbook you already keep.',
    icon: 'chart',
    riskTier: 'medium',
    source: 'bundled',
    eligible: true,
    ineligibleReasons: [],
    deprecated: null,
    yanked: false,
    sampleAvailable: true,
    ...overrides,
  };
}

export function detail(overrides: Partial<MarketDetail> = {}): MarketDetail {
  return {
    ...card(),
    description: 'Reads the receivables workbook and ranks overdue invoices by days late.',
    highlights: ['Ranks every customer by days overdue', 'Names the largest overdue balance', 'Never edits the workbook'],
    license: 'MIT',
    homepage: '',
    requires: {},
    minHost: '>=0.1.0',
    digest: 'sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
    signature: {
      status: 'signed',
      keyId: 'agent-desk-2026',
      fingerprint: 'SHA256:feedfacefeedfacefeedfacefeedface',
      signedAt: '2026-11-01T09:00:00Z',
    },
    provenance: { builder: 'agent-desk', sourceCommit: 'abc123def4567890' },
    capabilities: {
      sources: ['excel-watch'],
      permissions: ['filesystem.read: ${workspace}/finance/**'],
      elementKinds: ['metric', 'list'],
      filesystem: ['${workspace}/finance/**'],
      network: [],
    },
    changelog: { version: '1.2.0', text: 'Adds a days-late column and a largest-balance line.', date: '2026-11-01' },
    publishedAt: '2026-11-01T09:00:00Z',
    validation: { checkedAt: '2026-11-01T09:05:00Z', ok: true, failures: [] },
    ...overrides,
  };
}

export const SAMPLE: MarketSample = {
  elements: [
    { kind: 'metric', label: 'Overdue invoices', value: 12 },
    { kind: 'text', text: 'Largest balance: Meridian, 41 days late.' },
  ],
  status: 'fresh',
  cause: '',
  checked_at: '2026-11-01T09:05:00Z',
};

export function catalog(entries: MarketCard[] = [card()]): CatalogResponse {
  return {
    entries,
    total: entries.length,
    sources: [{ source: 'bundled', count: entries.length }],
    policy: { mode: 'curated', source: 'bundled', signatureStatus: 'required' },
  };
}

export function installed(overrides: Partial<InstalledSummary> = {}): InstalledSummary {
  return {
    id: 'ar-aging',
    name: 'AR Aging',
    version: '1.2.0',
    pinned: { version: '1.2.0', sha256: 'a'.repeat(64) },
    status: { status: 'enabled', cause: '', checked_at: '2026-11-01T09:05:00Z' },
    pilot: { views: 3, remaining: 2 },
    update: null,
    pendingConsent: false,
    shared: false,
    enabled: true,
    dataDirSize: 2048,
    ...overrides,
  };
}

export function installedResponse(records: InstalledSummary[] = [installed()]): InstalledResponse {
  return { plugins: records, policy: { mode: 'curated', source: 'bundled', signatureStatus: 'required' } };
}

export function detailResponse(overrides: Partial<DetailResponse> = {}): DetailResponse {
  return {
    plugin: detail(),
    installed: null,
    versions: [
      { version: '1.2.0', digest: 'sha256:0123456789abcdef', yanked: false },
      { version: '1.1.0', digest: 'sha256:fedcba9876543210', yanked: false },
    ],
    alternatives: [],
    sample: SAMPLE,
    ...overrides,
  };
}

export function pack(overrides: Partial<Pack> = {}): Pack {
  return {
    id: 'manager',
    name: 'Manager pack',
    audience: 'managers',
    summary: 'The weekly numbers a manager actually reads.',
    icon: 'folder',
    excluded: [{ id: 'competitor-watch', reason: 'network plugin, excluded from packs' }],
    sampleData: false,
    firstRun: true,
    plugins: [
      card({ id: 'ar-aging', name: 'AR Aging' }),
      card({ id: 'revenue-vs-target', name: 'Revenue vs target', category: 'finance', icon: 'chart' }),
    ],
    members: [
      {
        id: 'ar-aging', name: 'AR Aging', version: '1.2.0', eligible: true,
        ineligibleReasons: [], scopes: ['filesystem.read: ${workspace}/finance/**'],
      },
      {
        id: 'revenue-vs-target', name: 'Revenue vs target', version: '0.4.0', eligible: true,
        ineligibleReasons: [], scopes: ['filesystem.read: ${workspace}/sales/**'],
      },
    ],
    eligible: true,
    blockedMember: null,
    blockedReason: '',
    ...overrides,
  };
}

export function packs(packsList: Pack[] = [pack()]): PacksResponse {
  return {
    packs: packsList,
    total: packsList.length,
    policy: { mode: 'curated', source: 'bundled', signatureStatus: 'required' },
  };
}
