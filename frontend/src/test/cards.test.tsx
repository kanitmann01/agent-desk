// The card-contents ticket's behavior suite: the honest states of the
// sales, commitments, research, skills and plugin cards, with the
// content effects gone (no canvas, no per-character spectacle, no
// count-up).
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CommitmentsCard from '../dashboard/CommitmentsCard';
import PluginCardView from '../dashboard/PluginCardView';
import ResearchCard, { RESEARCH_BUSY } from '../dashboard/ResearchCard';
import SalesCard from '../dashboard/SalesCard';
import SkillsCard from '../dashboard/SkillsCard';
import { CellHead, HealthMatrix, StageChart } from '../dashboard/cells';
import type { SalesStatus } from '../types';

const NOOP_REFETCH = async () => {};
const NOOP_EXPIRED = () => {};

const HEALTHY_SALES: SalesStatus = {
  configured: true,
  state: 'healthy',
  path: 'C:\\Users\\priya\\Documents\\sales.xlsx',
  last_ok_ts: 1_700_000_000,
  delta: {
    added: [['row a'], ['row b']],
    removed: [['row c']],
    unchanged: 40,
  },
};

const COMMITMENTS_HEALTHY = {
  state: 'healthy',
  path: null,
  keyEvent: {
    id: 'evt-1',
    subject: 'Budget review',
    start: '2026-11-12T09:30:00',
    end: '2026-11-12T10:00:00',
    location: 'Teams',
    attendees: 4,
  },
  breakdown: {
    subtasks: ['Pull the October actuals', 'Draft the variance note'],
    followups: [{ text: 'Send the note to Amara', deadline: 'Friday' }],
  },
  checks: { 0: true },
  firstDetected: '2026-11-12T08:40:00',
  generatedAt: '2026-11-12T08:40:00',
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('the sales card', () => {
  it('reads the KPI as plain tabular numerals with its delta chips', () => {
    render(
      <SalesCard
        sales={{ enabled: true, mode: 'live', status: HEALTHY_SALES }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP_EXPIRED}
      />,
    );
    const value = document.querySelector('.kpi .value');
    expect(value).toHaveTextContent('3');
    expect(document.querySelector('.kpi-chip.up')).toHaveTextContent('+2 added');
    expect(document.querySelector('.kpi-chip.down')).toHaveTextContent('-1 removed');
    expect(screen.getByText('row a')).toBeInTheDocument();
    expect(screen.getByText('row c')).toBeInTheDocument();
    expect(document.querySelector('.card canvas')).toBeNull();
  });

  it('connects a workbook through the picker, then the manual path', async () => {
    const fetchMock = vi.fn(
      async (url: RequestInfo | URL, _init?: RequestInit) => {
        if (String(url).includes('/pick')) {
          return Response.json({ path: null });
        }
        return Response.json({});
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    const onRefetch = vi.fn(NOOP_REFETCH);
    const user = userEvent.setup();
    render(
      <SalesCard
        sales={{ enabled: true, mode: 'unconfigured', status: null }}
        onRefetch={onRefetch}
        onExpired={NOOP_EXPIRED}
      />,
    );
    expect(document.querySelector('.card canvas')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Connect a workbook' }));
    // The picker yielded nothing, so the manual path appears with its error.
    expect(
      await screen.findByText('The file dialog did not open. Type the workbook path below and press Connect.'),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText('Workbook path'), 'C:\\books\\sales.xlsx');
    await user.click(screen.getByRole('button', { name: 'Connect' }));
    const connectCall = fetchMock.mock.calls.find(([u]) => String(u) === '/sources/excel-watch');
    expect(connectCall?.[0]).toBe('/sources/excel-watch');
    // The manual form closes on success and the card returns to its
    // normal unconfigured prompt, fed by the refetch.
    expect(await screen.findByRole('button', { name: 'Connect a workbook' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Workbook path')).toBeNull();
    expect(onRefetch).toHaveBeenCalled();
  });

  it('offers Re-test with the plain-language cause when stale', async () => {
    const fetchMock = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) => Response.json({}),
    );
    vi.stubGlobal('fetch', fetchMock);
    const onRefetch = vi.fn(NOOP_REFETCH);
    const user = userEvent.setup();
    render(
      <SalesCard
        sales={{
          enabled: true,
          mode: 'live',
          status: { ...HEALTHY_SALES, state: 'stale', cause: 'The last hourly read failed.' },
        }}
        onRefetch={onRefetch}
        onExpired={NOOP_EXPIRED}
      />,
    );
    expect(screen.getByText(/shown as stale rather than current/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Re-test now' }));
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/retest'))).toBe(true);
    expect(onRefetch).toHaveBeenCalled();
  });

  it('says so when the re-test cannot reach the server', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('network down');
      }),
    );
    const onRefetch = vi.fn(NOOP_REFETCH);
    const user = userEvent.setup();
    render(
      <SalesCard
        sales={{
          enabled: true,
          mode: 'live',
          status: { ...HEALTHY_SALES, state: 'stale', cause: 'The last hourly read failed.' },
        }}
        onRefetch={onRefetch}
        onExpired={NOOP_EXPIRED}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Re-test now' }));
    expect(
      await screen.findByText('The dashboard could not reach its own server; the re-test did not run.'),
    ).toBeInTheDocument();
    expect(onRefetch).not.toHaveBeenCalled();
  });

  it('keeps a renamed title once the workbook is configured', () => {
    // The rename must survive the states the source enters when it
    // misbehaves, exactly because that is when the user is watching.
    render(
      <SalesCard
        sales={{ enabled: true, mode: 'live', status: HEALTHY_SALES }}
        title="Pipeline"
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP_EXPIRED}
      />,
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Pipeline' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: 'Sales, last 24 hours' })).toBeNull();
  });
});

describe('the commitments card', () => {
  const STATUS = COMMITMENTS_HEALTHY;

  it('shows the key event, the persisted checks and the follow-up chips', () => {
    render(
      <CommitmentsCard
        commitments={{ enabled: true, mode: 'live', status: STATUS }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP_EXPIRED}
      />,
    );
    expect(screen.getByText('Budget review')).toBeInTheDocument();
    expect(screen.getByText('Teams, 4 attendees')).toBeInTheDocument();
    const first = screen.getByRole('checkbox', { name: /Pull the October actuals/ });
    expect(first).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('checkbox', { name: /Draft the variance note/ })).toHaveAttribute(
      'aria-checked',
      'false',
    );
    expect(document.querySelector('.follow')).toHaveTextContent('Send the note to Amara, by Friday');
  });

  it('persists a check flip and refetches', async () => {
    const fetchMock = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) => Response.json({}),
    );
    vi.stubGlobal('fetch', fetchMock);
    const onRefetch = vi.fn(NOOP_REFETCH);
    const user = userEvent.setup();
    render(
      <CommitmentsCard
        commitments={{ enabled: true, mode: 'live', status: STATUS }}
        onRefetch={onRefetch}
        onExpired={NOOP_EXPIRED}
      />,
    );
    const second = screen.getByRole('checkbox', { name: /Draft the variance note/ });
    await user.click(second);
    const checkCall = fetchMock.mock.calls.find(([u]) => String(u).includes('/widgets/commitments/check'));
    expect(checkCall?.[0]).toBe('/widgets/commitments/check');
    expect(JSON.parse(String(checkCall?.[1]?.body)).checked).toBe(true);
    await vi.waitFor(() => expect(second).toHaveAttribute('aria-checked', 'true'));
    expect(onRefetch).toHaveBeenCalled();
  });

  it('keeps a renamed title in the unreadable state', () => {
    render(
      <CommitmentsCard
        commitments={{
          enabled: true,
          mode: 'live',
          status: { ...STATUS, state: 'unreadable', cause: 'The file is not calendar data.' },
        }}
        title="Today"
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP_EXPIRED}
      />,
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Today' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: "Today's key commitment" })).toBeNull();
  });
});

describe('the research card', () => {
  it('renders the answer as plain text with its sources, no spectacle', () => {
    render(
      <ResearchCard
        span="span-8"
        enabled
        lastAnsweredTs={null}
        answer={{ question: 'Who sells to Meridian?', summary: 'Two reps named Meridian.', sources: ['crm', 'notes'] }}
        answerSeq={1}
        statusText=""
      />,
    );
    expect(screen.getByText('Who sells to Meridian?')).toBeInTheDocument();
    expect(screen.getByText('Two reps named Meridian.')).toBeInTheDocument();
    expect(screen.getByText('crm')).toBeInTheDocument();
    expect(document.querySelector('.card canvas')).toBeNull();
  });

  it('states the busy status as honest text', () => {
    render(
      <ResearchCard
        span="span-8"
        enabled
        lastAnsweredTs={null}
        answer={null}
        answerSeq={0}
        statusText={RESEARCH_BUSY}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent(RESEARCH_BUSY);
    expect(document.querySelector('.card canvas')).toBeNull();
  });

  it('states the pause and the way back when research is off', () => {
    render(
      <ResearchCard
        span="span-8"
        enabled={false}
        lastAnsweredTs={null}
        answer={null}
        answerSeq={0}
        statusText=""
      />,
    );
    expect(screen.getByText('Paused')).toBeInTheDocument();
    expect(screen.getByText(/Research is turned off in settings\./)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Turn it back on' })).toHaveAttribute('href', '/settings');
    // Off is not an ask surface: no empty prompt suggesting one.
    expect(screen.queryByText(/No answer yet/)).toBeNull();
  });
});

describe('the skills card', () => {
  it('lists skills as real run buttons', async () => {
    const onRun = vi.fn();
    const user = userEvent.setup();
    render(
      <SkillsCard
        skills={[
          { id: 1, name: 'Monday numbers', description: 'Summarize the sheet' },
          { id: 2, name: 'Standup notes', description: '' },
        ]}
        busy={false}
        onRun={onRun}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Run Monday numbers' }));
    expect(onRun).toHaveBeenCalledWith(1);
    expect(screen.getByText('2 saved')).toBeInTheDocument();
  });

  it('ignores runs while a skill is already running', async () => {
    const onRun = vi.fn();
    const user = userEvent.setup();
    render(
      <SkillsCard skills={[{ id: 1, name: 'A', description: '' }]} busy onRun={onRun} />,
    );
    await user.click(screen.getByRole('button', { name: 'Run A' }));
    expect(onRun).not.toHaveBeenCalled();
  });
});

describe('the plugin card', () => {
  it('carries the pilot badge when new', () => {
    render(
      <PluginCardView
        card={{ id: 'p1', title: 'Invoice tracker', version: '1.2.0', pilot: true, state: 'active', freshness: 'fresh', cause: '' }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP_EXPIRED}
      />,
    );
    expect(screen.getByText('PILOT')).toHaveClass('badge-pilot');
    expect(document.querySelector('.stamp')).not.toHaveClass('amber');
  });

  it('draws lists, tables and statuses, not only metric and text', () => {
    render(
      <PluginCardView
        card={{
          id: 'outlook-digest',
          title: 'Outlook Brief',
          version: '0.3.0',
          pilot: true,
          state: 'enabled',
          freshness: 'fresh',
          cause: '',
          payload: {
            elements: [
              { kind: 'metric', value: '5', label: 'Active messages (24h)' },
              {
                kind: 'list',
                title: 'Active threads',
                rows: [
                  { primary: 'Q4 pipeline review', secondary: 'Priya Raman', meta: '3 msg · 2 h ago' },
                  { primary: 'Lunch on Friday?', secondary: 'Ana Souza', meta: '1 msg · 1 h ago' },
                ],
              },
              {
                kind: 'table',
                title: 'Reply starters',
                columns: ['Starter', 'Style'],
                rows: [['I am on it', 'Direct'], ['Could you confirm?', 'Clarify']],
              },
              { kind: 'status', text: 'Reading headers only', tone: 'ok' },
            ],
          },
        }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP_EXPIRED}
      />,
    );
    expect(screen.getByText('Active threads')).toBeInTheDocument();
    expect(screen.getByText('Q4 pipeline review')).toBeInTheDocument();
    expect(screen.getByText('3 msg · 2 h ago')).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByText('Could you confirm?')).toBeInTheDocument();
    expect(screen.getByText('Reading headers only')).toBeInTheDocument();
  });

  it('states the cause honestly under the amber pair when attention', () => {
    render(
      <PluginCardView
        card={{ id: 'p1', title: 'Invoice tracker', version: '1.2.0', pilot: true, state: 'active', freshness: 'attention', cause: 'data source has not run' }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP_EXPIRED}
      />,
    );
    expect(document.querySelector('.card')).toHaveClass('amber');
    expect(document.querySelector('.stamp')).toHaveClass('amber');
    expect(screen.getByText('data source has not run')).toBeInTheDocument();
    expect(screen.getByText(/Re-test runs the plugin's data source again/)).toBeInTheDocument();
  });

  it('re-tests from the overflow menu against the plugin endpoint, once', async () => {
    const fetchMock = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) => Response.json({}),
    );
    vi.stubGlobal('fetch', fetchMock);
    const onRefetch = vi.fn(async () => {});
    const user = userEvent.setup();
    render(
      <PluginCardView
        card={{ id: 'p1', title: 'Invoice tracker', version: '1.2.0', pilot: false, state: 'active', freshness: 'attention', cause: 'data source has not run' }}
        onRefetch={onRefetch}
        onExpired={NOOP_EXPIRED}
      />,
    );
    await user.click(screen.getByRole('button', { name: /^Widget options/ }));
    await user.click(screen.getByRole('menuitem', { name: 'Re-test now' }));
    const retestCall = fetchMock.mock.calls.find(([u]) => String(u) === '/api/marketplace/retest');
    expect(retestCall?.[0]).toBe('/api/marketplace/retest');
    expect(retestCall?.[1]?.body).toBe(JSON.stringify({ id: 'p1' }));
    await vi.waitFor(() => expect(onRefetch).toHaveBeenCalled());
  });

  it('disables the re-test item while one is already running', async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => { release = resolve; });
    vi.stubGlobal('fetch', vi.fn(async () => {
      await gate;
      return Response.json({});
    }));
    const user = userEvent.setup();
    render(
      <PluginCardView
        card={{ id: 'p1', title: 'Invoice tracker', version: '1.2.0', pilot: false, state: 'active', freshness: 'attention', cause: 'data source has not run' }}
        onRefetch={async () => {}}
        onExpired={NOOP_EXPIRED}
      />,
    );
    await user.click(screen.getByRole('button', { name: /^Widget options/ }));
    await user.click(screen.getByRole('menuitem', { name: 'Re-test now' }));
    // Open the menu again while the first re-test is still in flight.
    await user.click(screen.getByRole('button', { name: /^Widget options/ }));
    expect(screen.getByRole('menuitem', { name: 'Re-test now' })).toBeDisabled();
    release();
    // When the re-test settles, the item answers again.
    await vi.waitFor(() =>
      expect(screen.getByRole('menuitem', { name: 'Re-test now' })).toBeEnabled(),
    );
  });
});

describe('the card overflow menus', () => {
  it('offers Connect a workbook and Open settings when sales is unconfigured', async () => {
    const user = userEvent.setup();
    render(
      <SalesCard
        sales={{ enabled: true, mode: 'unconfigured', status: null }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP_EXPIRED}
      />,
    );
    await user.click(screen.getByRole('button', { name: /^Widget options/ }));
    const menu = screen.getByRole('menu', { name: /^Widget options/ });
    expect(menu).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Connect a workbook' })).toBeInTheDocument();
    const settings = screen.getByRole('menuitem', { name: 'Open settings' });
    expect(settings).toHaveAttribute('href', '/settings');
  });

  it('re-tests the sales source from the menu when live', async () => {
    const fetchMock = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) => Response.json({}),
    );
    vi.stubGlobal('fetch', fetchMock);
    const onRefetch = vi.fn(async () => {});
    const user = userEvent.setup();
    render(
      <SalesCard
        sales={{ enabled: true, mode: 'live', status: HEALTHY_SALES }}
        onRefetch={onRefetch}
        onExpired={NOOP_EXPIRED}
      />,
    );
    await user.click(screen.getByRole('button', { name: /^Widget options/ }));
    await user.click(screen.getByRole('menuitem', { name: 'Re-test now' }));
    const retestCall = fetchMock.mock.calls.find(([u]) => String(u) === '/sources/excel-watch/retest');
    expect(retestCall?.[0]).toBe('/sources/excel-watch/retest');
    await vi.waitFor(() => expect(onRefetch).toHaveBeenCalled());
  });

  it('offers Re-test, the walkthrough and settings on the commitments card', async () => {
    const fetchMock = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) => Response.json({}),
    );
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(
      <CommitmentsCard
        commitments={{ enabled: true, mode: 'live', status: { ...COMMITMENTS_HEALTHY, state: 'stale', cause: 'The OneDrive file is behind.' } }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP_EXPIRED}
      />,
    );
    await user.click(screen.getByRole('button', { name: /^Widget options/ }));
    await user.click(screen.getByRole('menuitem', { name: 'Re-test now' }));
    const retestCall = fetchMock.mock.calls.find(([u]) => String(u) === '/sources/calendar-bridge/retest');
    expect(retestCall?.[0]).toBe('/sources/calendar-bridge/retest');
  });

  it('offers Connect your calendar when the calendar is empty', async () => {
    const user = userEvent.setup();
    render(
      <CommitmentsCard
        commitments={{ enabled: true, mode: 'live', status: { ...COMMITMENTS_HEALTHY, state: 'empty' } }}
        onRefetch={NOOP_REFETCH}
        onExpired={NOOP_EXPIRED}
      />,
    );
    await user.click(screen.getByRole('button', { name: /^Widget options/ }));
    const connect = screen.getByRole('menuitem', { name: 'Connect your calendar' });
    expect(connect).toHaveAttribute('href', '/walkthrough/calendar');
    expect(screen.getByRole('menuitem', { name: 'Open settings' })).toHaveAttribute('href', '/settings');
    const path = screen.getByText('agent-desk/calendar_sync.json');
    expect(path.tagName).toBe('CODE');
    expect(path).toHaveClass('nowrap');
    expect(path.textContent).toBe('agent-desk/calendar_sync.json');
  });

  it('carries Open settings on the research and skills cards', async () => {
    const user = userEvent.setup();
    render(
      <ResearchCard
        span="span-8"
        enabled
        lastAnsweredTs={null}
        answer={null}
        answerSeq={0}
        statusText=""
      />,
    );
    await user.click(screen.getByRole('button', { name: /^Widget options/ }));
    expect(screen.getByRole('menuitem', { name: 'Open settings' })).toHaveAttribute('href', '/settings');
    cleanup();
    render(
      <SkillsCard
        skills={[{ id: 1, name: 'Monday numbers', description: '' }]}
        busy={false}
        onRun={() => {}}
      />,
    );
    await user.click(screen.getByRole('button', { name: /^Widget options/ }));
    expect(screen.getByRole('menuitem', { name: 'Open settings' })).toHaveAttribute('href', '/settings');
  });
});

describe('the cell text-fit markup', () => {
  it('gives a cell tag a title so a clipped tag stays reachable', () => {
    render(<CellHead tag="DESK HEALTH" meta={<span className="mono">2/3 live</span>} />);
    expect(screen.getByRole('heading', { name: 'DESK HEALTH' }))
      .toHaveAttribute('title', 'DESK HEALTH');
  });

  it('titles every source row and keeps the numbers in their numeric cells', () => {
    render(
      <HealthMatrix
        rows={[{ name: 'Workbook', live: true, status: 'live', lastRun: '15:05', items: '1,234,567' }]}
      />,
    );
    expect(screen.getAllByRole('columnheader')).toHaveLength(4);
    expect(screen.getByRole('rowheader', { name: 'Workbook' }))
      .toHaveAttribute('title', 'Workbook');
    expect(document.querySelector('.matrix td.num.mono')).toHaveTextContent('15:05');
  });

  it('titles the stage axis labels, so the ellipsis has a reachable value', () => {
    render(<StageChart stages={[{ stage: 'Prospect', deals: 3, net: 4 }]} />);
    const span = document.querySelector('.stage-axis span');
    expect(span).toHaveAttribute('title', 'Prospect');
    expect(span?.querySelector('small')).toHaveAttribute('title', '3 deals');
  });
});
