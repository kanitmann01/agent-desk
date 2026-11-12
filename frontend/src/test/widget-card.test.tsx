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
  it('renders title, freshness stamp, overflow menu, body and foot', () => {
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
    expect(screen.getByRole('button', { name: 'Widget options' })).toBeInTheDocument();
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
