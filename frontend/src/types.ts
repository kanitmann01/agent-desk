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

export interface PluginCard {
  id: string;
  title: string;
  version: string;
  pilot: boolean;
  state: string;
  freshness: string; // fresh | attention
  cause: string;
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
  plugins: { cards: PluginCard[] };
}
