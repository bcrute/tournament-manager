/**
 * Who is signed in, asked once.
 *
 * `SiteNav` renders on every page outside the room, and each account screen
 * needs the same answer, so a plain `useEffect` fetch per component would ask
 * the server the same question three times on one navigation. The answer is
 * cached at module scope and pushed to every listener instead.
 *
 * It is a cache, not a source of truth: the session is an httpOnly cookie and
 * the server decides. Anything that changes the account — signing in or out,
 * a rename — calls `publishAccount` so the nav stops showing a stale name.
 */

import { useEffect, useState } from "react";
import { Account, getAccount } from "./api";

/** `undefined` means "not asked yet", which is not the same as signed out and
 *  must not render as it — a flash of "Sign in" for someone who is signed in
 *  is the bug this distinction exists to prevent. */
export type AccountState = Account | null | undefined;

let cache: AccountState = undefined;
let inflight: Promise<void> | null = null;
const listeners = new Set<(a: AccountState) => void>();

export function publishAccount(a: AccountState) {
  cache = a;
  for (const l of listeners) l(a);
}

/** Forget the cached answer so the next mount asks again. */
export function resetAccountCache() {
  cache = undefined;
  inflight = null;
  listeners.clear();
}

function load(): Promise<void> {
  // one request even when three components mount in the same tick
  inflight ??= getAccount()
    .then((r) => publishAccount(r.account))
    .catch(() => publishAccount(null))
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

export function useAccount(): AccountState {
  const [acct, setAcct] = useState<AccountState>(cache);

  useEffect(() => {
    listeners.add(setAcct);
    if (cache === undefined) void load();
    else setAcct(cache);
    return () => {
      listeners.delete(setAcct);
    };
  }, []);

  return acct;
}
