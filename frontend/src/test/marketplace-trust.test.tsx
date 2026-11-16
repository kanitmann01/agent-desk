// The trust center must report the recorded state honestly: no run means no
// run, and a policy warning is shown in amber rather than hidden.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarketplaceApp from '../marketplace/MarketplaceApp';

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

function trustSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    anchor: { epoch: 3, fingerprints: ['a24fafdbac6e'] },
    policy: {
      mode: 'open',
      source: 'signed',
      signatureStatus: 'signed',
      warning: null as string | null,
      epoch: 3,
      signerFingerprint: 'deadbeef',
      expiresAt: '2027-11-15T12:00:00Z',
    },
    lastValidatorRun: {
      at: null as string | null,
      ok: null as boolean | null,
      failures: [] as { code: string; message: string }[],
      scope: null as string | null,
    },
    guarantees: [
      'Every release is checked against its signed digest before it can become eligible.',
      'A signed policy pins the risk ceiling, allowed sources and network allowlist.',
    ],
    cannotHappen: [
      'A tampered or expired policy can never be applied by the marketplace.',
      'The browser can never edit the policy file.',
    ],
    reportPath: '/marketplace/report',
    ...overrides,
  };
}

describe('Trust center', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/marketplace/trust');
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, '', '/');
  });

  it('shows the anchor, signature state and an honest empty validator run', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(trustSnapshot())));
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Trust center' })).toBeInTheDocument();
    expect(screen.getByText('a24fafdbac6e')).toBeInTheDocument();
    expect(screen.getByText('deadbeef')).toBeInTheDocument();
    expect(screen.getByText('No validator run has been recorded yet. This is not a pass; nothing has been checked on this desk so far.')).toBeInTheDocument();
    expect(screen.getByText('Every release is checked against its signed digest before it can become eligible.')).toBeInTheDocument();
    expect(screen.getByText('A tampered or expired policy can never be applied by the marketplace.')).toBeInTheDocument();
    expect(screen.getByText('/marketplace/report')).toBeInTheDocument();
  });

  it('shows the policy warning and the recorded validator failures', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(trustSnapshot({
      policy: {
        mode: 'curated',
        source: 'built-in',
        signatureStatus: 'tampered',
        warning: 'The imported policy bundle was rejected (policy:bad-signature). The built-in curated policy stays active.',
        epoch: 3,
        signerFingerprint: 'deadbeef',
        expiresAt: '2027-11-15T12:00:00Z',
      },
      lastValidatorRun: {
        at: '2026-11-15T12:00:00Z',
        ok: false,
        scope: 'policy',
        failures: [{ code: 'policy:bad-signature', message: 'the policy signature does not verify' }],
      },
    }))));
    render(<MarketplaceApp />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Trust center' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('rejected (policy:bad-signature)');
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('policy:bad-signature')).toBeInTheDocument();
    expect(screen.getByText('the policy signature does not verify')).toBeInTheDocument();
  });
});
