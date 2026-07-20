export interface CardInfo {
  id: number;
  name: string;
  role: string;
  rarity: string;
  text: string;
  uri: string;
  artist: string;
  rulings: string[];
  image: string;
}

export interface PlayerInfo {
  pid: number;
  name: string;
  isHost: boolean;
  revealed: boolean;
  left: boolean;
  eliminated: boolean;
  /** Declared unable to lose — thresholds stop being flagged for them. */
  cantLose: boolean;
  isMe: boolean;
  life: number | null;
  cmdDamage: Record<string, number>;
  card: CardInfo | null;
}

export type RoomStatus = "lobby" | "playing" | "ended";
export type GameMode = "life" | "treachery";

export interface LogEntry {
  at: number;
  text: string;
}

/** Present only when this room backs a tournament pod. */
export interface RoomTournament {
  code: string;
  name: string;
  podId: number;
  table: number;
  round: number;
  roundStatus: string;
  endsAt: number | null;
  pausedAt: number | null;
  /** Non-null once time has been called: additional turns still to play. */
  turnsRemaining: number | null;
  now: number;
}

export interface RoomState {
  log: LogEntry[];
  tournament: RoomTournament | null;
  room: {
    code: string;
    urlId: string;
    status: RoomStatus;
    mode: GameMode;
    startingLife: number;
    gameNo: number;
    firstPid: number | null;
    firstPlayer: string | null;
    options: { rarities?: string[] };
    displays: number;
    distribution: Record<string, number>;
  };
  players: PlayerInfo[];
  me: {
    pid: number;
    name: string;
    isHost: boolean;
    isDisplay: boolean;
    /** Showing the table view on their own phone, while keeping their seat. */
    isTracker: boolean;
    cantLose: boolean;
    revealed: boolean;
    eliminated: boolean;
    life: number | null;
    cmdDamage: Record<string, number>;
    card: CardInfo | null;
  };
}

export interface SeatInfo {
  pid: number;
  name: string;
  vacant: boolean;
  eliminated: boolean;
}

export interface SeatsResponse {
  status: RoomStatus;
  mode: GameMode;
  seats: SeatInfo[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api/table";

export async function api<T>(
  path: string,
  opts: { method?: string; token?: string; body?: unknown } = {},
): Promise<T> {
  const r = await fetch(BASE + path, {
    method: opts.method ?? "GET",
    headers: {
      ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(opts.token ? { "X-Player-Token": opts.token } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((d: { detail?: string }) => d.detail)
      .catch(() => undefined);
    throw new ApiError(r.status, detail ?? r.statusText);
  }
  return r.json() as Promise<T>;
}
