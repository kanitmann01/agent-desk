// The pending primitive: a button that says it is working without moving,
// and the delay hook that keeps a flash under 100 ms from reading as a
// glitch. The CSS contract is read from the authored sheet, as the token
// suite does.
import { act, cleanup, render, renderHook, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Button from '../components/Button';
import { useBusy } from '../components/useBusy';

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(resolve(here, '..', 'index.css'), 'utf8');

afterEach(() => {
  cleanup();
});

// The text of one CSS block, balanced to its closing brace.
function balancedBlock(source: string, marker: string): string {
  const start = source.indexOf(marker);
  if (start === -1) return '';
  let depth = 0;
  for (let i = start + marker.length - 1; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  return '';
}

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return css.match(new RegExp(`${escaped}\\{([^}]*)\\}`))?.[1] ?? '';
}

describe('the button when nothing is pending', () => {
  it('renders no busy attribute, no dot and its normal label', () => {
    render(<Button onClick={() => {}}>Save</Button>);
    const button = screen.getByRole('button', { name: 'Save' });
    expect(button).not.toHaveAttribute('aria-busy');
    expect(button).toBeEnabled();
    expect(button).toHaveTextContent('Save');
    expect(button.querySelector('.btn-busy-dot')).toBeNull();
    expect(button.querySelector('.btn-labels')).toBeNull();
  });
});

describe('the button while pending', () => {
  it('announces busy and stops accepting activation', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<Button pending onClick={onClick}>Save</Button>);
    const button = screen.getByRole('button', { name: 'Save' });
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(button).toBeDisabled();
    await user.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('exposes only the pending label and hides the dot from assistive technology', () => {
    render(<Button pending pendingLabel="Saving...">Save</Button>);
    const button = screen.getByRole('button', { name: 'Saving...' });
    expect(button).toHaveAccessibleName('Saving...');
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull();
    const dot = button.querySelector('.btn-busy-dot');
    expect(dot).not.toBeNull();
    expect(dot).toHaveAttribute('aria-hidden', 'true');
  });

  it('keeps both labels in one cell and hides the inactive one with a class', () => {
    render(<Button pending pendingLabel="Saving...">Save</Button>);
    const button = screen.getByRole('button', { name: 'Saving...' });
    expect(button.querySelector('.btn-labels')).not.toBeNull();
    const labels = Array.from(button.querySelectorAll('.btn-label'));
    expect(labels).toHaveLength(2);
    const idle = labels.find((label) => label.textContent === 'Save');
    const pending = labels.find((label) => label.textContent === 'Saving...');
    expect(idle).toHaveClass('btn-label-hidden');
    expect(idle).toHaveAttribute('aria-hidden', 'true');
    expect(pending).not.toHaveClass('btn-label-hidden');
    expect(pending).not.toHaveAttribute('aria-hidden');
  });

  it('falls back to the normal label as the pending label', () => {
    render(<Button pending>Save</Button>);
    const button = screen.getByRole('button', { name: 'Save' });
    expect(button).toHaveAccessibleName('Save');
    expect(button.querySelectorAll('.btn-label')).toHaveLength(2);
  });
});

describe('useBusy', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('stays false below the delay and turns true at 100 ms', () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useBusy(true));
    expect(result.current).toBe(false);
    act(() => {
      vi.advanceTimersByTime(99);
    });
    expect(result.current).toBe(false);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe(true);
  });

  it('turns false the moment active turns false', () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ active }) => useBusy(active), {
      initialProps: { active: true },
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(result.current).toBe(true);
    rerender({ active: false });
    expect(result.current).toBe(false);
  });

  it('never shows busy for a flap shorter than the delay', () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ active }) => useBusy(active), {
      initialProps: { active: true },
    });
    act(() => {
      vi.advanceTimersByTime(60);
    });
    rerender({ active: false });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(result.current).toBe(false);
  });

  it('clears its timer on unmount', () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useBusy(true));
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
    act(() => {
      vi.advanceTimersByTime(500);
    });
  });

  it('does not warn about an act update', () => {
    vi.useFakeTimers();
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      const { result, rerender, unmount } = renderHook(
        ({ active }) => useBusy(active),
        { initialProps: { active: true } },
      );
      act(() => {
        vi.advanceTimersByTime(100);
      });
      expect(result.current).toBe(true);
      rerender({ active: false });
      expect(result.current).toBe(false);
      unmount();
      act(() => {
        vi.advanceTimersByTime(100);
      });
    } finally {
      const messages = error.mock.calls.flat().map(String).join('\n');
      error.mockRestore();
      expect(messages).not.toContain('not wrapped in act');
    }
  });
});

describe('the stylesheet carries the pending contract', () => {
  it('draws an 8px dot on a semantic token and pulses it like setup-picking', () => {
    const dot = rule('.btn-busy-dot');
    expect(dot).toContain('width:8px');
    expect(dot).toContain('height:8px');
    expect(dot).toContain('border-radius:50%');
    expect(dot).toMatch(/background:var\(--(live|accent)\)/);
    expect(dot).toContain('animation:setup-pick .9s ease-in-out infinite');
  });

  it('pulses by opacity only, with no transform in its keyframes', () => {
    const dot = rule('.btn-busy-dot');
    const name = /animation:([\w-]+)/.exec(dot)?.[1] ?? '';
    expect(name).not.toBe('');
    const frames = balancedBlock(css, `@keyframes ${name}{`);
    expect(frames).not.toBe('');
    expect(frames).toContain('opacity');
    expect(frames).not.toContain('transform');
    expect(frames).not.toContain('translate');
  });

  it('freezes the dot under reduced motion', () => {
    const reduced = balancedBlock(css, '@media (prefers-reduced-motion:reduce){');
    expect(reduced).not.toBe('');
    expect(reduced).toContain('.btn-busy-dot{animation:none}');
  });

  it('stacks both labels in one grid cell and hides the inactive one', () => {
    expect(rule('.btn-labels')).toContain('display:grid');
    expect(rule('.btn-label')).toContain('grid-area:1/1');
    expect(rule('.btn-label-hidden')).toContain('visibility:hidden');
  });

  it('marks the busy control as progress and dims it like disabled', () => {
    const busy = rule('.btn-pending:disabled');
    expect(busy).toContain('cursor:progress');
    expect(busy).toContain('opacity:');
  });
});
