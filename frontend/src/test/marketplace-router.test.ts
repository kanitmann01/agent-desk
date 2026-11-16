// The router contract: a pure parse table for every marketplace route and
// a history hook whose back button is the browser's, not a re-render trick.
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { parseRoute, useMarketplaceRouter } from '../marketplace/router';

const TABLE: Array<[string, string, Record<string, string>]> = [
  ['/marketplace', 'discover', {}],
  ['/marketplace/', 'discover', {}],
  ['/marketplace/search', 'search', { q: '' }],
  ['/marketplace/search?q=overdue+invoices', 'search', { q: 'overdue invoices' }],
  ['/marketplace/search?q=overdue%20invoices%20%26%20cash', 'search', { q: 'overdue invoices & cash' }],
  ['/marketplace/category/finance', 'category', { category: 'finance' }],
  ['/marketplace/category/finance/', 'category', { category: 'finance' }],
  ['/marketplace/plugin/ar-aging', 'plugin', { id: 'ar-aging' }],
  ['/marketplace/plugin/ar-aging/', 'plugin', { id: 'ar-aging' }],
  ['/marketplace/plugin/plugin%2Fwith%2Fslash', 'plugin', { id: 'plugin/with/slash' }],
  ['/marketplace/plugin/ar-aging/manage', 'manage', { id: 'ar-aging' }],
  ['/marketplace/manage/ar-aging', 'manage', { id: 'ar-aging' }],
  ['/marketplace/pack/manager', 'pack', { id: 'manager' }],
  ['/marketplace/installed', 'installed', {}],
  ['/marketplace/publishers', 'publishers', {}],
  ['/marketplace/publisher/agent-desk', 'publisher', { name: 'agent-desk' }],
  ['/marketplace/studio', 'studio', {}],
  ['/marketplace/admin', 'admin', {}],
  ['/marketplace/trust', 'trust', {}],
  ['/marketplace/trust/', 'trust', {}],
];

describe('parseRoute', () => {
  it.each(TABLE)('parses %s', (input, name, params) => {
    expect(parseRoute(input)).toEqual({ name, params });
  });

  it('ignores a hash and keeps parsing the path', () => {
    expect(parseRoute('/marketplace/installed#plugins')).toEqual({ name: 'installed', params: {} });
  });

  it.each([
    '/marketplace/unknown',
    '/marketplace/plugin',
    '/marketplace/plugin/ar-aging/manage/extra',
    '/marketplace/pack/manager/extra',
    '/elsewhere',
    '/',
  ])('renders not-found for %s instead of a blank page', (input) => {
    const route = parseRoute(input);
    expect(route.name).toBe('notfound');
    expect(route.params.path).toBeTruthy();
  });

  it('keeps a live path when decoding is impossible', () => {
    expect(parseRoute('/marketplace/plugin/%E0%A4%A')).toEqual({
      name: 'plugin', params: { id: '%E0%A4%A' },
    });
  });
});

describe('the marketplace history hook', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/marketplace');
  });
  afterEach(() => {
    window.history.replaceState({}, '', '/');
  });

  it('starts from the address bar, so a refresh on a deep link keeps the route', () => {
    window.history.replaceState({}, '', '/marketplace/plugin/ar-aging');
    const { result } = renderHook(() => useMarketplaceRouter());
    expect(result.current.path).toBe('/marketplace/plugin/ar-aging');
    expect(result.current.route).toEqual({ name: 'plugin', params: { id: 'ar-aging' } });
  });

  it('pushes a new entry and follows the browser back button', async () => {
    const { result } = renderHook(() => useMarketplaceRouter());
    act(() => result.current.navigate('/marketplace/installed'));
    expect(result.current.route.name).toBe('installed');
    act(() => result.current.navigate('/marketplace/studio'));
    expect(result.current.route.name).toBe('studio');
    const length = window.history.length;

    act(() => window.history.back());
    await waitFor(() => expect(result.current.route.name).toBe('installed'));
    expect(result.current.path).toBe('/marketplace/installed');

    act(() => window.history.forward());
    await waitFor(() => expect(result.current.route.name).toBe('studio'));
    expect(window.history.length).toBe(length);
  });

  it('replaces the entry for a filter commit without growing history', () => {
    const { result } = renderHook(() => useMarketplaceRouter());
    const before = window.history.length;
    act(() => result.current.navigate('/marketplace/search?q=overdue', true));
    expect(result.current.route).toEqual({ name: 'search', params: { q: 'overdue' } });
    expect(window.history.length).toBe(before);
  });
});
