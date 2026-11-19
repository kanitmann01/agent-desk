// The theme control. Two sizes of one radio group: the Settings tiles
// (canvas and accent shown as a swatch, the name under it) and the
// compact strip in the rail footer (three swatches). Arrow keys move
// between themes, as in any radio group.
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { THEMES, applyTheme, currentTheme, type ThemeId } from './theme';

interface ThemePickerProps {
  compact?: boolean;
}

/**
 * The current theme and a setter that applies it.
 *
 * The value follows the agentdesk:theme event, so every mounted picker and any
 * other control that applies a theme stays in step.
 */
export function useTheme(): [ThemeId, (id: ThemeId) => void] {
  const [theme, setTheme] = useState<ThemeId>(() => currentTheme());
  useEffect(() => {
    /** Follow a theme applied anywhere in the page, not only by this picker. */
    const onChange = (event: Event) => setTheme((event as CustomEvent<ThemeId>).detail);
    window.addEventListener('agentdesk:theme', onChange);
    return () => window.removeEventListener('agentdesk:theme', onChange);
  }, []);
  return [theme, (id: ThemeId) => { applyTheme(id); setTheme(id); }];
}

/**
 * The theme control: tiles in Settings, a strip of swatches in the rail.
 *
 * One radio group in both sizes: arrow keys move and wrap, and only the
 * selected option is in the tab order.
 */
export default function ThemePicker({ compact = false }: ThemePickerProps) {
  const [theme, choose] = useTheme();
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  /** Move the choice one option in the arrow's direction, wrapping at both ends. */
  function onKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1
      : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const next = (index + step + THEMES.length) % THEMES.length;
    choose(THEMES[next].id);
    refs.current[next]?.focus();
  }

  return (
    <div
      className={compact ? 'theme-strip' : 'theme-tiles'}
      role="radiogroup"
      aria-label="Theme"
    >
      {THEMES.map((option, index) => {
        const selected = option.id === theme;
        return (
          <button
            key={option.id}
            ref={(node) => { refs.current[index] = node; }}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={compact ? `${option.name} theme` : undefined}
            title={compact ? option.name : undefined}
            tabIndex={selected ? 0 : -1}
            className={compact ? 'theme-dot' : 'theme-tile'}
            data-theme-option={option.id}
            onClick={() => choose(option.id)}
            onKeyDown={(event) => onKey(event, index)}
          >
            {/* The swatch resolves the theme's own tokens in a preview
                scope, so the picker carries no colour of its own. */}
            <span className="theme-swatch" data-theme-preview={option.id} aria-hidden="true">
              <span className="theme-swatch-accent" />
            </span>
            {compact ? null : (
              <span className="theme-tile-text">
                <span className="theme-tile-name">{option.name}</span>
                <span className="theme-tile-note">{option.note}</span>
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
