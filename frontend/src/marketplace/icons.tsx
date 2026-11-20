// Inline SVG glyphs for the manifest icon enum. No emoji, no icon font:
// every glyph is a 24px stroke drawing that inherits currentColor.
import type { ReactNode } from 'react';

export type IconName =
  | 'calendar' | 'chart' | 'mail' | 'book' | 'checklist'
  | 'clock' | 'alert' | 'folder' | 'plugin' | 'generic';

const PATHS: Record<IconName, ReactNode> = {
  calendar: (
    <>
      <rect x="4" y="5" width="16" height="15" rx="2" />
      <path d="M8 3v4M16 3v4M4 10h16" />
    </>
  ),
  chart: (
    <>
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </>
  ),
  mail: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </>
  ),
  book: (
    <>
      <path d="M5 4h9a3 3 0 0 1 3 3v13H8a3 3 0 0 0-3 3Z" />
      <path d="M5 4v16M17 8h2v14h-2" />
    </>
  ),
  checklist: (
    <>
      <path d="M4 6h2M4 12h2M4 18h2M10 6h10M10 12h10M10 18h10" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3 2 21h20Z" />
      <path d="M12 9v5M12 17.5v.5" />
    </>
  ),
  folder: (
    <>
      <path d="M3 7h7l2 2h9v10H3Z" />
    </>
  ),
  plugin: (
    <>
      <path d="M9 3v4M15 3v4M6 7h12v6a6 6 0 0 1-12 0Z" />
      <path d="M12 16v5" />
    </>
  ),
  generic: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8 12h8M12 8v8" />
    </>
  ),
};

/**
 * Coerce a manifest icon name to a glyph this module can draw.
 *
 * Anything unknown, including an absent name, becomes `generic`, so a
 * manifest can never break the icon set.
 */
export function normalizeIcon(name: string | undefined): IconName {
  if (name && name in PATHS) return name as IconName;
  return 'generic';
}

/**
 * Draw a plugin's glyph as inline SVG that inherits `currentColor`.
 *
 * The drawing is decorative: it is hidden from assistive technology, so the
 * label beside it has to carry the meaning.
 */
export function PluginIcon({ name, size = 22 }: { name?: string; size?: number }) {
  return (
    <svg
      className="mkt-glyph"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[normalizeIcon(name)]}
    </svg>
  );
}

/** Draw the decorative magnifier at its fixed 18px size. */
export function SearchGlyph() {
  return (
    <svg className="mkt-search-glyph" width="18" height="18" viewBox="0 0 24 24"
         fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

/** Draw the decorative copy-to-clipboard glyph at its fixed 14px size. */
export function CopyGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15H4V4h11v1" />
    </svg>
  );
}

/** Draw the decorative confirmation check at its fixed 14px size. */
export function CheckGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="m4 12 5 5L20 6" />
    </svg>
  );
}
