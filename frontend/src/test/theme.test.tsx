import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import ThemePicker from '../theme/ThemePicker';
import { THEME_KEY, storedTheme } from '../theme/theme';

beforeEach(() => {
  localStorage.clear();
  document.documentElement.dataset.theme = 'unkey';
});

afterEach(() => {
  cleanup();
});

describe('the theme picker', () => {
  it('offers exactly the three desk themes as a radio group', () => {
    render(<ThemePicker />);
    const group = screen.getByRole('radiogroup', { name: 'Theme' });
    expect(group.querySelectorAll('[role="radio"]')).toHaveLength(3);
    expect(screen.getByRole('radio', { name: /Unkey/ })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: /Coforge/ })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Momentuum blue/ })).toBeInTheDocument();
  });

  it('switching theme updates the root attribute and persists', async () => {
    const user = userEvent.setup();
    render(<ThemePicker />);
    await user.click(screen.getByRole('radio', { name: /Coforge/ }));
    expect(document.documentElement.dataset.theme).toBe('coforge');
    expect(localStorage.getItem(THEME_KEY)).toBe('coforge');
    expect(storedTheme()).toBe('coforge');
    expect(screen.getByRole('radio', { name: /Coforge/ })).toHaveAttribute('aria-checked', 'true');
  });

  it('moves with the arrow keys like any radio group', async () => {
    const user = userEvent.setup();
    render(<ThemePicker compact />);
    const unkey = screen.getByRole('radio', { name: 'Unkey theme' });
    unkey.focus();
    await user.keyboard('{ArrowRight}{ArrowRight}');
    expect(document.documentElement.dataset.theme).toBe('momentuum');
    expect(localStorage.getItem(THEME_KEY)).toBe('momentuum');
    expect(screen.getByRole('radio', { name: 'Momentuum blue theme' })).toHaveFocus();
  });

  it('ignores a stored value that is not a theme', () => {
    localStorage.setItem(THEME_KEY, 'cisco-momentum');
    expect(storedTheme()).toBe('unkey');
  });
});
