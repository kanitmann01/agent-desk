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
export interface PluginElement {
  kind: 'metric' | 'text';
  label?: string;
  value?: string;
  text?: string;
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
  payload?: { elements: PluginElement[] } | null;
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

export interface DashboardData {
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
  skills: { id: number; name: string; description: string }[];
  layout: { cards: LayoutCard[] };
  plugins: { cards: PluginCard[] };
}
