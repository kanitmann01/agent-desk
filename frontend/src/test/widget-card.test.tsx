// The card-system ticket's behavior suite: the three-part header
// contract on paper lift, the stamp's status dot, the plain Button and
// the shared empty state.
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Button from '../components/Button';
import EmptyState, { ICON_SEARCH } from '../components/EmptyState';
import Stamp from '../components/Stamp';
import WidgetCard from '../components/WidgetCard';

afterEach(() => {
  cleanup();
});

describe('the widget card header contract', () => {
  it('renders title, freshness stamp, body and foot', () => {
    render(
      <WidgetCard
        title="Sales, last 24h"
        span="span-7"
        stamp={{ fresh: true, text: 'updated 3 min ago' }}
        foot={<span>foot text</span>}
      >
        <p>body copy</p>
      </WidgetCard>,
    );
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Sales, last 24h');
    expect(screen.getByText('updated 3 min ago')).toBeInTheDocument();
    // No menu items declared: the dots are not rendered, so no dead
    // control ships. The regex matches the real accessible name shape.
    expect(screen.queryByRole('button', { name: /^Widget options/ })).toBeNull();
    expect(screen.getByText('body copy')).toBeInTheDocument();
    expect(screen.getByText('foot text')).toBeInTheDocument();
    // The card body is the article itself: no glass wrapper between.
    expect(document.querySelector('.card > article.widget')).not.toBeNull();
    expect(document.querySelector('.card > article.widget canvas')).toBeNull();
  });

  it('carries the pilot badge beside the title', () => {
    render(
      <WidgetCard
        title="Follow-ups"
        span="span-5"
        badge="pilot"
        stamp={{ fresh: true, text: 'Ready' }}
        foot="note"
      >
        <p>body</p>
      </WidgetCard>,
    );
    expect(screen.getByText('pilot')).toHaveClass('badge-pilot');
  });

  it('turns the stamp into the amber pair when stale and keeps the card paper-white', () => {
    render(
      <WidgetCard
        title="Calendar"
        span="span-5"
        amber
        stamp={{ fresh: false, text: 'stale 2h ago' }}
        foot="note"
      >
        <p>body</p>
      </WidgetCard>,
    );
    const card = document.querySelector('.card');
    expect(card).toHaveClass('amber');
    const stamp = document.querySelector('.stamp');
    expect(stamp).toHaveClass('amber');
    expect(screen.getByText('stale 2h ago')).toBeInTheDocument();
    // The stamp mark is the 7px status dot, not a drawn badge.
    expect(stamp?.querySelector('.dot')).not.toBeNull();
    expect(stamp?.querySelector('svg')).toBeNull();
  });

  it('reserves two foot lines and centers sparse bodies', () => {
    render(
      <WidgetCard
        title="T"
        span="span-4"
        sparse
        footLines={2}
        stamp={{ fresh: true, text: 'Ready' }}
        foot="note"
      >
        <p>body</p>
      </WidgetCard>,
    );
    expect(document.querySelector('.w-foot.two-line')).not.toBeNull();
    expect(document.querySelector('.w-body.sparse')).not.toBeNull();
  });

  it('lands in the requested grid span', () => {
    render(
      <WidgetCard title="T" span="span-8" stamp={{ fresh: true, text: 'Ready' }} foot="note">
        <p>body</p>
      </WidgetCard>,
    );
    expect(document.querySelector('.cell.span-8')).not.toBeNull();
  });

  it('marks a header with a menu so the menu keeps its own gutter', () => {
    render(
      <WidgetCard
        title="T"
        span="span-4"
        stamp={{ fresh: true, text: 'Ready' }}
        menuItems={[{ label: 'Open settings', href: '/settings' }]}
        foot="note"
      >
        <p>body</p>
      </WidgetCard>,
    );
    const head = document.querySelector('.w-head');
    expect(head).toHaveClass('has-menu');
    // The trigger stays in the header, so the dots are in the card's top
    // right rather than at the end of a squeezed title row.
    const trigger = screen.getByRole('button', { name: 'Widget options, T' });
    expect(trigger.closest('.w-head')).toBe(head);
  });

  it('leaves the menu gutter off a header with no menu', () => {
    render(
      <WidgetCard title="T" span="span-4" stamp={{ fresh: true, text: 'Ready' }} foot="note">
        <p>body</p>
      </WidgetCard>,
    );
    expect(document.querySelector('.w-head')).not.toHaveClass('has-menu');
  });
});

describe('the widget card overflow menu', () => {
  const MENU_ITEMS = [
    { label: 'Re-test now', onSelect: vi.fn() },
    { label: 'Open settings', onSelect: vi.fn() },
  ];

  function renderWithMenu() {
    MENU_ITEMS.forEach((item) => { item.onSelect.mockClear(); });
    render(
      <WidgetCard
        title="Sales, last 24h"
        span="span-7"
        stamp={{ fresh: true, text: 'Ready' }}
        menuItems={MENU_ITEMS}
        foot="note"
      >
        <p>body copy</p>
      </WidgetCard>,
    );
  }

  it('declares the trigger, opens the menu and fires one item once', async () => {
    const user = userEvent.setup();
    renderWithMenu();
    const trigger = screen.getByRole('button', { name: 'Widget options, Sales, last 24h' });
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await user.click(trigger);
    const menu = screen.getByRole('menu', { name: 'Widget options, Sales, last 24h' });
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(menu).toBeInTheDocument();
    const retest = screen.getByRole('menuitem', { name: 'Re-test now' });
    expect(screen.getByRole('menuitem', { name: 'Open settings' })).toBeInTheDocument();
    await user.click(retest);
    expect(MENU_ITEMS[0].onSelect).toHaveBeenCalledTimes(1);
    expect(MENU_ITEMS[1].onSelect).not.toHaveBeenCalled();
    // The action closes the menu and the trigger is the focus again.
    expect(screen.queryByRole('menu')).toBeNull();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveFocus();
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    const user = userEvent.setup();
    renderWithMenu();
    const trigger = screen.getByRole('button', { name: 'Widget options, Sales, last 24h' });
    await user.click(trigger);
    expect(screen.getByRole('menu')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).toBeNull();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveFocus();
    // Escape fired no action.
    expect(MENU_ITEMS.every((item) => item.onSelect.mock.calls.length === 0)).toBe(true);
  });

  it('closes when the pointer goes down outside the menu', async () => {
    const user = userEvent.setup();
    renderWithMenu();
    const trigger = screen.getByRole('button', { name: 'Widget options, Sales, last 24h' });
    await user.click(trigger);
    expect(screen.getByRole('menu')).toBeInTheDocument();
    await user.click(document.body);
    expect(screen.queryByRole('menu')).toBeNull();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });

  it('keeps the menu open across a re-render that does not change the items', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <WidgetCard title="T" span="span-7" stamp={{ fresh: true, text: 'Ready' }}
        menuItems={MENU_ITEMS} foot="note"><p>body</p></WidgetCard>,
    );
    await user.click(screen.getByRole('button', { name: 'Widget options, T' }));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    rerender(
      <WidgetCard title="T" span="span-7" stamp={{ fresh: true, text: 'Ready' }}
        menuItems={MENU_ITEMS} foot="note"><p>other body</p></WidgetCard>,
    );
    expect(screen.getByRole('menu')).toBeInTheDocument();
  });

  it('takes focus when it opens, walks with the arrow keys and Home and End', async () => {
    const user = userEvent.setup();
    renderWithMenu();
    const trigger = screen.getByRole('button', { name: 'Widget options, Sales, last 24h' });
    await user.click(trigger);
    // Opening puts focus on the first item, so the arrows work at once.
    const first = screen.getByRole('menuitem', { name: 'Re-test now' });
    const second = screen.getByRole('menuitem', { name: 'Open settings' });
    expect(first).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(second).toHaveFocus();
    // The walk wraps instead of stopping at the ends.
    await user.keyboard('{ArrowDown}');
    expect(first).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(second).toHaveFocus();
    await user.keyboard('{End}');
    expect(second).toHaveFocus();
    await user.keyboard('{Home}');
    expect(first).toHaveFocus();
  });
});

describe('the stamp', () => {
  it('reads fresh with the green dot and no pill', () => {
    render(<Stamp fresh text="updated 3 min ago" />);
    const stamp = document.querySelector('.stamp');
    expect(stamp).not.toHaveClass('amber');
    expect(stamp?.querySelector('.dot')).not.toBeNull();
    expect(stamp?.querySelector('.dot.amber')).toBeNull();
    expect(stamp?.querySelector('svg')).toBeNull();
  });

  it('reads stale with the amber dot', () => {
    render(<Stamp fresh={false} text="stale 2h ago" />);
    expect(document.querySelector('.stamp .dot.amber')).not.toBeNull();
  });

  it('titles and focuses the stamp so a clipped status stays reachable', () => {
    render(<Stamp fresh={false} text="Re-test available" />);
    const stamp = document.querySelector('.stamp');
    expect(stamp).toHaveAttribute('title', 'Re-test available');
    expect(stamp).toHaveAttribute('tabindex', '0');
  });

  it('copes with an empty time', () => {
    render(<Stamp fresh={false} text="" />);
    expect(document.querySelector('.stamp .dot.amber')).not.toBeNull();
  });
});

describe('the plain button', () => {
  it('renders the primary tone as a real button that answers clicks', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<Button tone="primary" onClick={onClick}>Re-test</Button>);
    const button = screen.getByRole('button', { name: 'Re-test' });
    expect(button).toHaveClass('btn-primary');
    await user.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('passes type through, so a button can submit its form', () => {
    render(<Button tone="primary" type="submit">Add plugin</Button>);
    expect(screen.getByRole('button', { name: 'Add plugin' })).toHaveAttribute(
      'type',
      'submit',
    );
  });

  it('renders a href as a link styled as the button', () => {
    render(<Button tone="primary" href="/settings">Turn it back on</Button>);
    const link = screen.getByRole('link', { name: 'Turn it back on' });
    expect(link).toHaveClass('btn-primary');
    expect(link.tagName).toBe('A');
  });

  it('stays in the tree but stops answering while disabled', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<Button disabled onClick={onClick}>Busy</Button>);
    const button = screen.getByRole('button', { name: 'Busy' });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe('the shared empty state', () => {
  it('pairs the icon, the message and the action in one row', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(
      <EmptyState icon={ICON_SEARCH} action={<Button tone="primary" onClick={onClick}>Connect the workbook</Button>}>
        The workbook is not connected yet.
      </EmptyState>,
    );
    expect(document.querySelector('.empty-state .empty-icon')).not.toBeNull();
    expect(screen.getByText('The workbook is not connected yet.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Connect the workbook' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
