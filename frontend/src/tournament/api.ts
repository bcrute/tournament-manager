/**
 * Tournament API client.
 *
 * Organizer calls ride the account session cookie; player calls carry an
 * entrant token as a query parameter on reads only. Everything is a plain
 * fetch — one snapshot per poll, no per-row requests.
 */

export class TourneyError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api/tournament";

export async function tapi<T>(
  path: string,
  opts: { method?: string; body?: unknown } = {},
): Promise<T> {
  const r = await fetch(BASE + path, {
    method: opts.method ?? "GET",
    headers: opts.body !== undefined ? { "Content-Type": "application/json" } : {},
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((d: { detail?: string }) => d.detail)
      .catch(() => undefined);
    throw new TourneyError(r.status, detail ?? r.statusText);
  }
  return r.json() as Promise<T>;
}

export interface PodSeat {
  seat: number;
  /** Opaque and tournament-scoped — never the database's own id. */
  entrantId: string;
  name: string;
  place: number | null;
  points: number | null;
}

export interface PodView {
  podId: number;
  table: number;
  status: "pending" | "active" | "awaiting_result" | "complete";
  roomCode: string | null;
  extensionSeconds: number;
  seats: PodSeat[];
  /** Present only on the viewer's own pod. */
  roomToken?: string | null;
  mySeat?: number;
}

export interface StandingRow {
  entrantId: string;
  name: string;
  points: number;
  opponentPoints: number;
  podsPlayed: number;
  claimed: boolean;
  dropped: boolean;
  rank: number;
}

export interface OfficialCall {
  id: number;
  podId: number | null;
  status: "open" | "acknowledged";
  category: string | null;
  note: string | null;
  createdAt: number;
  /** How long the table has been waiting, and the time that buys them back. */
  openSeconds: number;
  suggestedMinutes: number;
}

export interface TournamentState {
  tournament: {
    code: string;
    name: string;
    /** Which game profile this event runs. MTG is one surface, not the base. */
    game: string;
    mode: string;
    status: "setup" | "running" | "ended";
    settings: Record<string, unknown>;
    roundCount: number;
  };
  round: {
    number: number;
    status: "pending" | "active" | "closed";
    endsAt: number | null;
    pausedAt: number | null;
    now: number;
  } | null;
  pods: PodView[];
  myPod: PodView | null;
  me: { entrantId: string; name: string } | null;
  standings: StandingRow[];
  calls: OfficialCall[];
  isOrganizer: boolean;
}

export interface RosterEntry {
  entrantId: string;
  name: string;
  claimed: boolean;
  dropped: boolean;
}

export interface GameProfile {
  key: string;
  name: string;
  publisher: string;
  defaultPodSize: number;
  modes: string[];
  resource: string;
  timeCalledPolicies: string[];
  sanctioningAccount: string | null;
}

export const listGames = () => tapi<{ games: GameProfile[] }>("/games");

export const createTournament = (
  name: string,
  mode: string,
  settings: Record<string, unknown>,
  game = "mtg",
) => tapi<{ code: string; game: string }>("", {
  method: "POST",
  body: { name, game, mode, settings },
});

export const getState = (code: string, token?: string | null) =>
  tapi<TournamentState>(`/${code}${token ? `?token=${encodeURIComponent(token)}` : ""}`);

export const getRoster = (code: string) =>
  tapi<{ name: string; status: string; entrants: RosterEntry[] }>(`/${code}/roster`);

export const claimSeat = (code: string, entrantId: string, wizardsEmail?: string) =>
  tapi<{ entrantToken: string; entrantId: string; name: string }>(`/${code}/claim`, {
    method: "POST",
    body: { entrantId, wizardsEmail: wizardsEmail ?? null },
  });

export const addEntrants = (code: string, names: string[]) =>
  tapi<{ added: { entrantId: string; name: string }[] }>(`/${code}/entrants`, {
    method: "POST",
    body: { names },
  });

export const releaseEntrant = (code: string, id: string) =>
  tapi<{ ok: boolean }>(`/${code}/entrants/${id}/release`, { method: "POST" });

export const dropEntrant = (code: string, id: string) =>
  tapi<{ ok: boolean }>(`/${code}/entrants/${id}/drop`, { method: "POST" });

export const openRound = (code: string, reroll = false) =>
  tapi<{ round: number; pods: unknown[] }>(`/${code}/rounds`, {
    method: "POST",
    body: { reroll },
  });

export const callTime = (code: string) =>
  tapi<{ ok: boolean; decided: number; policy: string }>(`/${code}/rounds/time`, {
    method: "POST",
  });

export const undropEntrant = (code: string, id: string) =>
  tapi<{ ok: boolean }>(`/${code}/entrants/${id}/undrop`, { method: "POST" });

export const endTournament = (code: string) =>
  tapi<{ ok: boolean; standings: StandingRow[] }>(`/${code}/end`, { method: "POST" });

export const closeRound = (code: string) =>
  tapi<{ ok: boolean }>(`/${code}/rounds/close`, { method: "POST" });

export const reportResult = (
  code: string,
  podId: number,
  body: { kind: string; places?: { entrantId: string; place: number }[]; note?: string },
) => tapi<{ ok: boolean; version: number }>(`/${code}/pods/${podId}/result`, {
  method: "POST",
  body,
});

export const timerAction = (
  code: string,
  action: "start" | "pause" | "resume" | "extend",
  extra: { minutes?: number; podId?: number } = {},
) => tapi<{ ok: boolean }>(`/${code}/timer`, { method: "POST", body: { action, ...extra } });

export const callOfficial = (code: string, podId: number, token: string, note?: string) =>
  tapi<{ ok: boolean }>(`/${code}/pods/${podId}/call?token=${encodeURIComponent(token)}`, {
    method: "POST",
    body: { note: note ?? null },
  });

export const ackCall = (code: string, id: number) =>
  tapi<{ ok: boolean }>(`/${code}/calls/${id}/ack`, { method: "POST" });

/**
 * Resolve a call. Omitting `extendMinutes` lets the server give the table back
 * the time it measured; pass a number (including 0) to override the judge's
 * way.
 */
export const resolveCall = (code: string, id: number, extendMinutes?: number, note?: string) =>
  tapi<{
    ok: boolean;
    openSeconds: number;
    suggestedMinutes: number;
    grantedMinutes: number;
    grantedBy: "measured" | "judge" | "off";
  }>(`/${code}/calls/${id}/resolve`, {
    method: "POST",
    body: { note: note ?? null, extendMinutes: extendMinutes ?? null },
  });

/** Player-side persistence: which tournament seat this device holds. */
const SEAT_KEY = "tournament.seat";

export interface SeatSession {
  code: string;
  token: string;
  entrantId: string;
  name: string;
}

export function loadSeat(): SeatSession | null {
  try {
    const raw = localStorage.getItem(SEAT_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as SeatSession;
    return s && typeof s.code === "string" && typeof s.token === "string" ? s : null;
  } catch {
    return null;
  }
}

export function saveSeat(s: SeatSession) {
  localStorage.setItem(SEAT_KEY, JSON.stringify(s));
}

export function clearSeat() {
  localStorage.removeItem(SEAT_KEY);
}

/** Seconds left on the round clock, corrected for client clock skew. */
export function secondsLeft(round: TournamentState["round"], nowMs: number, offsetMs: number) {
  if (!round?.endsAt) return null;
  if (round.pausedAt) return Math.max(0, round.endsAt - round.pausedAt);
  return Math.max(0, Math.round(round.endsAt - (nowMs + offsetMs) / 1000));
}

export function formatClock(seconds: number | null) {
  if (seconds === null) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
