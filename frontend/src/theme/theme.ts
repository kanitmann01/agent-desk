// The three desk themes. The choice lives on <html data-theme>, which
// the stylesheet reads, and in localStorage under one key, so every
// page of the app (the SPA and the server pages) opens in the same
// theme. public/theme-boot.js applies the stored theme before the
// first paint; this module changes it afterwards.

export type ThemeId = 'unkey' | 'coforge' | 'momentuum';

export interface ThemeOption {
  id: ThemeId;
  name: string;
  note: string;
}

export const THEME_KEY = 'agentdesk.theme';
export const DEFAULT_THEME: ThemeId = 'unkey';

export const THEMES: readonly ThemeOption[] = [
  { id: 'unkey', name: 'Unkey', note: 'Dark, yellow-green' },
  { id: 'coforge', name: 'Coforge', note: 'Navy, coral' },
  { id: 'momentuum', name: 'Momentuum blue', note: 'Light, brand blue' },
];

/** True when a value is one of the theme ids the app ships. */
export function isThemeId(value: unknown): value is ThemeId {
  return THEMES.some((theme) => theme.id === value);
}

/**
 * Read the theme saved in this browser, or the default when none is saved.
 *
 * A stored id the app no longer ships and a storage that throws (private mode)
 * both read as the default.
 */
export function storedTheme(): ThemeId {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return isThemeId(value) ? value : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

/** The theme the document is wearing, falling back to the stored one. */
export function currentTheme(): ThemeId {
  const value = document.documentElement.dataset.theme;
  return isThemeId(value) ? value : storedTheme();
}

/** Apply a theme to the document and remember it. */
export function applyTheme(id: ThemeId): void {
  const root = document.documentElement;
  root.dataset.theme = id;
  syncThemeColor();
  try {
    localStorage.setItem(THEME_KEY, id);
  } catch {
    // Private mode: the theme still applies for this page.
  }
  window.dispatchEvent(new CustomEvent('agentdesk:theme', { detail: id }));
}

/** Match the browser chrome to the canvas the stylesheet resolved. */
export function syncThemeColor(): void {
  const meta = document.querySelector('meta[name="theme-color"]');
  const canvas = getComputedStyle(document.documentElement).getPropertyValue('--canvas').trim();
  if (meta && canvas) meta.setAttribute('content', canvas);
}
