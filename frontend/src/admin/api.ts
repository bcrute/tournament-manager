/**
 * Admin API client.
 *
 * The surface is unlisted, not secret. Every call here fails with 404 unless
 * the session belongs to a configured admin — the server decides, and this
 * client assumes nothing.
 */

export class AdminError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api/admin";

export async function adm<T>(
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
    throw new AdminError(r.status, detail ?? r.statusText);
  }
  return r.json() as Promise<T>;
}

export interface Overview {
  admin: string;
  rooms: { total: number; active: number; lobby: number };
  tournaments: { total: number; running: number };
  accounts: number;
  players: number;
  bans: number;
}

export interface AdminRoom {
  code: string;
  status: string;
  mode: string;
  game_no: number;
  created_at: number;
  last_active: number | null;
  players: number;
}

export interface AdminTournament {
  code: string;
  name: string;
  status: string;
  game: string;
  created_at: number;
  last_active: number | null;
  entrants: number;
}

export interface Ban {
  subject: string;
  until: number;
  strikes: number;
  last_strike: number | null;
}

export interface LogEntry {
  at: number;
  actor: string;
  action: string;
  target: string | null;
  detail: string | null;
}

export const getOverview = () => adm<Overview>("/overview");
export const getRooms = () => adm<{ rooms: AdminRoom[] }>("/rooms");
export const getTournaments = () => adm<{ tournaments: AdminTournament[] }>("/tournaments");
export const getBans = () => adm<{ bans: Ban[] }>("/bans");
export const getLog = () => adm<{ entries: LogEntry[] }>("/log");

export interface SecurityEntry {
  at: number;
  kind: string;
  subject: string | null;
  detail: string | null;
}

export const getSecurity = (kind?: string) =>
  adm<{ entries: SecurityEntry[]; last24h: { kind: string; n: number }[] }>(
    `/security${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`,
  );

export const closeRoom = (code: string, reason?: string) =>
  adm<{ ok: boolean }>(`/rooms/${code}/close`, { method: "POST", body: { reason: reason ?? null } });

export const endTournament = (code: string, reason?: string) =>
  adm<{ ok: boolean }>(`/tournaments/${code}/end`, {
    method: "POST",
    body: { reason: reason ?? null },
  });

export const liftBan = (subject: string, reason?: string) =>
  adm<{ ok: boolean }>(`/bans/${encodeURIComponent(subject)}/lift`, {
    method: "POST",
    body: { reason: reason ?? null },
  });

/** Unix seconds to something readable at a glance. */
export function ago(ts: number | null, now = Date.now()): string {
  if (!ts) return "—";
  const s = Math.max(0, Math.round(now / 1000 - ts));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}
