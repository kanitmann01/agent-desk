// The GET /api/dashboard payload, typed end to end. Shapes follow the
// server exactly (see dashboard_payload in app.py and the status() dicts
// of the excel watch and calendar bridge); field names keep the server's
// spelling, including the snake_case the watchers have always used.

export interface DeltaPayload {
  added: unknown[][];
  removed: unknown[][];
  unchanged?: number;
}

export interface SalesStatus {
  configured: boolean;
  state: string; // not_configured | first | healthy | stale | locked | unreadable
  cause?: string;
  path?: string;
  delta?: DeltaPayload | null;
  rowsSeen?: number;
  examples?: unknown[][];
  last_ok_ts?: number | null;
}

export interface KeyEvent {
  id: string;
  subject: string;
  start: string;
  end: string;
  location: string;
  attendees: number;
}

export interface Breakdown {
  subtasks?: string[];
  followups?: { text: string; deadline?: string }[];
}

export interface CommitmentsStatus {
  state: string; // healthy | clear | empty | stale | unreadable
  cause?: string;
  path?: string | null;
  keyEvent?: KeyEvent | null;
  breakdown?: Breakdown | null;
  checks?: Record<string, boolean>;
  firstDetected?: string | null;
  generatedAt?: string | null;
}

// One bound ui-schema element the host computed for a plugin widget:
// metric (a value with a label) or text (a note line). Anything the
// host could not bind is dropped server-side, never invented here.
export interface PluginListRow {
  primary?: string;
  secondary?: string;
  meta?: string;
}

export interface PluginTimelineItem {
  time?: string;
  title?: string;
  meta?: string;
}

export interface PluginChecklistItem {
  text?: string;
  done?: boolean;
  due?: string;
}

export interface PluginElement {
  kind:
    | 'metric'
    | 'text'
    | 'delta'
    | 'progress'
    | 'list'
    | 'table'
    | 'sparkline'
    | 'status'
    | 'timeline'
    | 'checklist';
  label?: string;
  title?: string;
  value?: string | number | null;
  text?: string;
  direction?: string;
  points?: number[];
  rows?: PluginListRow[] | string[][];
  columns?: string[];
  items?: PluginTimelineItem[] | PluginChecklistItem[];
  target?: number | null;
  unit?: string;
  tone?: 'ok' | 'attention' | 'alarm';
  reason?: string;
}

export interface PluginSetup {
  pluginId: string;
  instanceId: string;
  name: string;
  step: string;
}

export interface TrackerView {
  name: string;
  value: string;
  unit: string;
  delta: string;
  direction: string;
  points: number[];
  chart?: 'line' | 'column' | 'area' | string;
  axis?: 'time' | 'reading' | string;
  labels?: string[];
  deltaLabel?: string;
  seriesNote?: string;
  file: string;
  rowsSeen?: number;
  /** Epoch seconds of the reading behind this card. */
  readAt?: number;
  /** True when the reading comes from the app's own sample folder. */
  sample?: boolean;
  paceNote?: string;
  goal?: { value: string; unit: string } | null;
}

// One line under a card's reading. The server resolved it from the names the
// family declared (receipts from what the reading used, a note when it has
// something to explain), so a surface prints the text as it came and never
// keeps a phrase table of its own.
export interface InsightBlock {
  kind: 'receipts' | 'note';
  text: string;
}

// The one model call a reading may offer. Nothing is spent until the
// person presses the button the label sits on, so the label says what the
// press does rather than what the card is. The payload is the request: it
// travels to the route verbatim, minus the label and the route themselves.
export interface InsightPress {
  label: string;
  route: string;
  kind: 'reply-draft' | 'explain-range';
  /** The thread a reply drafts from, nested as the digest family emits it. */
  thread?: { subject: string; sender?: string; last?: string };
  /** The one sentence an explanation explains, as the workbook emits it. */
  text?: string;
}

// payload.insight: the reading behind a card's extra elements, its resolved
// lines, and the press when the family offered one.
export interface InsightReading {
  status: 'ok' | 'empty' | 'unavailable';
  source: string;
  /** Keys of the person's own settings that changed this reading. */
  preferences?: string[];
  note?: string;
  /** The lines under the card, already resolved and in print order. */
  blocks?: InsightBlock[];
  press?: InsightPress | null;
}

// POST /api/insight/draft, answered. 'draft' covers both a drafted reply
// and an explanation: what the press asked for decides which. 'staged' is
// the follow-up answer to a reply draft, false when a card already existed.
export interface InsightAnswer {
  status: 'draft' | 'empty';
  text: string;
  source: 'model' | 'template' | 'none';
  disclosure: string[];
  note: string;
  thread?: { id: string; to: string; subject: string };
  staged?: boolean;
  cardId?: string;
}

// A refused press. The sentence is written for the person and is shown as
// it came, never replaced by a status code.
export interface InsightRefusal {
  error: string;
  code: string;
}

export interface PluginCard {
  id: string;
  title: string;
  version: string;
  pilot: boolean;
  state: string;
  freshness: string; // fresh | attention
  cause: string;
  checkedAt?: string;
  pluginId?: string;
  instanceId?: string;
  payload?: {
    elements: PluginElement[];
    setup?: PluginSetup;
    tracker?: TrackerView;
    insight?: InsightReading;
  } | null;
}

// One card in the dashboard's layout as the payload lists it: visible
// cards only, in render order, a custom title riding along when the
// user renamed the card (null means the card's default display name).
export interface LayoutCard {
  key: string; // "sales" | "commitments" | "research" | "skills" | plugin id
  title: string | null;
}

// The full layout GET /api/layout returns and POST /api/layout takes:
// every card, hidden ones included, in the desired order.
export interface LayoutCardState {
  key: string;
  hidden: boolean;
  title: string | null;
}

// What one desk check found, as GET /api/desk-check lists it. The
// dashboard only needs the summary, but the settings section renders
// every field the API sends.
export interface DeskCheckFinding {
  id: string;
  title: string;
  cause: string;
  severity: 'info' | 'attention' | 'fatal';
  confident: boolean;
  fix: 'auto' | 'ask' | 'link' | 'none';
  fixLabel: string;
  href: string;
  detail: Record<string, unknown>;
}

// The dashboard's read-only summary: how many findings want attention,
// and the one the health cell names (the first fatal, else the first).
export interface DeskCheckSummary {
  attention: number;
  top: DeskCheckFinding | null;
}

// A deadline the desk found in a saved fact, shaped by the screens #195
// added to /api/dashboard. cites holds fact ids only, never the fact text.
export interface Recommendation {
  cardId: string;
  title: string;
  why: string;
  whySource: 'rule' | 'model';
  score: number | null;
  due: string | null;
  href: string;
  actionLabel: string;
  sample: boolean;
  cites: number[];
}

// The agent loop's dashboard summary (spec 016 #194): when the supervised
// loop last ran a pass and when the next one is due. enabled false means
// the interval is Off in settings; the last-run time still shows, because
// when the desk last checked does not depend on the cadence.
export interface AgentLoopSummary {
  lastRunTs: number | null;
  nextRunTs: number | null;
  enabled: boolean;
}

// The update summary (spec 016 #201): the staged-version banner, whether a
// share is set, and whether installs are on. banner is null unless a version
// is waiting for a restart or the last one rolled back.
export interface UpdateSummary {
  banner: string | null;
  available: string | null;
  autoUpdate: boolean;
  channelSet: boolean;
  lastResult: string;
}

/** One step of the Get started strip: what to connect, and whether it is. */
export interface SetupStep {
  id: 'ai' | 'workbook' | 'calendar';
  title: string;
  reason: string;
  /** The page a link opens. */
  href: string;
  /** The form a one-click button posts to, or null when the step is only a link. */
  action: string | null;
  /** True only when something real is connected; the sample set never counts. */
  done: boolean;
}

/** The three steps between a fresh desk and the morning loop. */
export interface SetupData {
  steps: SetupStep[];
  /** True while the desk is showing the labelled sample set. */
  sample: boolean;
  /** True while the strip should offer sample data: until a real
   *  workbook or calendar is connected. The AI key is not a source and
   *  does not withdraw the offer. */
  sampleOffer: boolean;
}

export interface DashboardData {
  sample?: boolean;
  /** Absent only on a server older than spec 022. */
  setup?: SetupData;
  version: string;
  flags: {
    excelEnabled: boolean;
    calendarEnabled: boolean;
    endpointEnabled: boolean;
  };
  sources: {
    connected: number;
    total: number;
    items: { id: string; status: string; detail: string }[];
  };
  sales: {
    enabled: boolean;
    mode: 'disabled' | 'unconfigured' | 'live';
    status: SalesStatus | null;
  };
  commitments: {
    enabled: boolean;
    mode: 'disabled' | 'unavailable' | 'live';
    status: CommitmentsStatus | null;
  };
  research: {
    enabled: boolean;
    lastAnsweredTs: number | null;
  };
  inbox: { waiting: number };
  deskCheck?: DeskCheckSummary;
  recommendations?: Recommendation[];
  agentLoop?: AgentLoopSummary;
  update?: UpdateSummary;
  skills: { id: number; name: string; description: string }[];
  layout: { cards: LayoutCard[] };
  plugins: { cards: PluginCard[] };
}
