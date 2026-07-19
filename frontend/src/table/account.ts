/** Optional accounts. Everything here degrades to anonymous play. */

export interface Account {
  username: string;
  hasEmail: boolean;
  createdAt: number;
}

export interface HistoryGame {
  roomCode: string;
  playedAs: string;
  mode: "life" | "treachery";
  status: string;
  gameNo: number;
  life: number | null;
  eliminated: boolean;
  at: number;
  note: string | null;
}

export interface StoredNote {
  roomCode: string;
  gameNo: number;
  text: string;
  updatedAt: number;
}

export class AccountError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api/account";

export async function account<T>(
  path: string,
  opts: { method?: string; body?: unknown } = {},
): Promise<T> {
  const r = await fetch(BASE + path, {
    method: opts.method ?? "GET",
    headers: opts.body !== undefined ? { "Content-Type": "application/json" } : {},
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin", // the session is an httpOnly cookie
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((d: { detail?: string }) => d.detail)
      .catch(() => undefined);
    throw new AccountError(r.status, detail ?? r.statusText);
  }
  return r.json() as Promise<T>;
}

export const getAccount = () => account<{ account: Account | null }>("/me");

export const signup = (username: string, password: string) =>
  account<{ account: Account; recoveryCodes: string[] }>("/signup", {
    method: "POST",
    body: { username, password },
  });

export const login = (username: string, password: string) =>
  account<{ account: Account }>("/login", { method: "POST", body: { username, password } });

export const logout = () => account<{ ok: boolean }>("/logout", { method: "POST" });

export const getHistory = () => account<{ games: HistoryGame[] }>("/history");

export const getNote = (code: string, gameNo: number) =>
  account<{ text: string; updatedAt: number | null }>(`/notes/${code}/${gameNo}`);

export const saveNote = (code: string, gameNo: number, text: string) =>
  account<{ ok: boolean }>(`/notes/${code}/${gameNo}`, { method: "PUT", body: { text } });
