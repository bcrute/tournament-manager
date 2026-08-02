/**
 * Accounts. Optional for playing — everything here degrades to anonymous play —
 * but required for hosting a tournament, which additionally needs a *confirmed*
 * recovery email. See `tournament/Host.tsx`.
 *
 * Confirmed is the word that carries weight. `hasEmail` used to flip true the
 * moment an address was stored; it now means the owner clicked a link sent to
 * it, and `emailPending` is the state in between.
 */

import { apiMessage } from "../retryAfter";

export interface Account {
  /** Typed to sign in: unique, and changing it costs a password. */
  username: string;
  /** Pre-filled when this account sits down at a table. Null means the device
   *  decides, which is how every account behaved before this existed. */
  displayName: string | null;
  /** A recovery address that has been **confirmed**. Nothing else counts. */
  hasEmail: boolean;
  /** An address is on file and waiting for its link to be clicked. */
  emailPending: boolean;
  /** Whether this deployment can send mail at all. False means the recovery
   *  codes are the only path, and the UI should say that rather than offering
   *  a form that will 503. */
  mailConfigured: boolean;
  createdAt: number;
}

/** What every email route answers with: the account, plus whether a message
 *  went out. The address itself is never returned by anything — see
 *  `TestRecoveryEmailIsWriteOnly`. */
export interface EmailResult extends Account {
  ok: boolean;
  sent?: boolean;
}

/** Totals across the whole history, not the page `/history` returns. */
export interface AccountStats {
  /** Times you sat down. A room can run several games from one seat, so this
   *  is what the seat rows can actually support — see the server's docstring. */
  games: number;
  tables: number;
  eliminated: number;
  notes: number;
  firstAt: number | null;
  lastAt: number | null;
  byMode: Record<string, number>;
  memberSince: number;
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
    throw new AccountError(
      r.status,
      apiMessage(r.status, detail ?? r.statusText, r.headers.get("Retry-After")),
    );
  }
  return r.json() as Promise<T>;
}

export const getAccount = () => account<{ account: Account | null }>("/me");

/** Username and password only. A recovery email is enrolled and confirmed
 *  separately, from account settings — see the server's SignupBody. */
export const signup = (username: string, password: string) =>
  account<{ account: Account; recoveryCodes: string[] }>("/signup", {
    method: "POST",
    body: { username, password },
  });

export const login = (username: string, password: string) =>
  account<{ account: Account }>("/login", { method: "POST", body: { username, password } });

export const logout = () => account<{ ok: boolean }>("/logout", { method: "POST" });

export const getHistory = (limit?: number) =>
  account<{ games: HistoryGame[] }>(limit ? `/history?limit=${limit}` : "/history");

export const getStats = () => account<AccountStats>("/stats");

export const getNotes = () => account<{ notes: StoredNote[] }>("/notes");

/** Renaming needs the password as well as the session: it is the one change
 *  the owner cannot undo unaided. See the server handler. */
export const changeUsername = (username: string, password: string) =>
  account<{ account: Account }>("/username", {
    method: "POST",
    body: { username, password },
  });

/** Empty clears it, putting the device's own last name back in charge. */
export const setDisplayName = (displayName: string) =>
  account<{ ok: boolean; displayName: string | null }>("/display-name", {
    method: "POST",
    body: { displayName },
  });

/**
 * Add or replace the recovery address. The password is required: this is the
 * setting that can hand the account to whoever holds the address, so pointing
 * it somewhere else is a takeover step rather than a preference.
 *
 * Nothing is confirmed by this call — it sends a link and returns with
 * `emailPending` true.
 */
export const setEmail = (email: string, password: string) =>
  account<EmailResult>("/email", { method: "POST", body: { email, password } });

/** Remove it. Also the password, and for the same reason. */
export const removeEmail = (password: string) =>
  account<EmailResult>("/email", { method: "POST", body: { email: null, password } });

/** Send the confirmation again. No password — it can only reach an address the
 *  owner already chose, and choosing it cost one. */
export const resendVerification = () =>
  account<EmailResult>("/email/resend", { method: "POST" });

/** Confirm an address from the link. No session: the link is opened from an
 *  inbox, routinely on a different device from the one that asked. */
export const verifyEmail = (token: string) =>
  account<EmailResult>("/email/verify", { method: "POST", body: { token } });

/**
 * Start a password reset. Always succeeds and always says the same thing —
 * whether the account exists, whether it has an address, and whether that
 * address is confirmed are all things this must not reveal.
 */
export const forgotPassword = (username: string) =>
  account<{ ok: boolean; message: string }>("/forgot", {
    method: "POST",
    body: { username },
  });

/** Finish it. Ends every session and signs this one in. */
export const resetPassword = (token: string, password: string) =>
  account<{ account: Account }>("/reset", { method: "POST", body: { token, password } });

/** Every other device is signed out, which is the server's behaviour, not a
 *  courtesy — a password change that leaves old sessions alive is not one. */
export const changePassword = (current: string, next: string) =>
  account<{ ok: boolean }>("/password", { method: "POST", body: { current, new: next } });

/** Replaces every unused code. The previous set stops working. */
export const regenerateRecoveryCodes = () =>
  account<{ recoveryCodes: string[] }>("/recovery-codes", { method: "POST" });

export const getNote = (code: string, gameNo: number) =>
  account<{ text: string; updatedAt: number | null }>(`/notes/${code}/${gameNo}`);

export const saveNote = (code: string, gameNo: number, text: string) =>
  account<{ ok: boolean }>(`/notes/${code}/${gameNo}`, { method: "PUT", body: { text } });

export const deleteAccount = (confirm: string) =>
  account<{ ok: boolean }>("/delete", { method: "POST", body: { confirm } });
