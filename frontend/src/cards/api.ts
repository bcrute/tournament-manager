/**
 * Card ruling lookup.
 *
 * Everything goes through our own backend, which then talks to Scryfall. That
 * is not indirection for its own sake: the CSP is `default-src 'self'` and
 * `e2e/privacy.spec.ts` asserts no page here makes a third-party request, so
 * fetching from the browser was never available. It is also the better shape —
 * Scryfall learns that this server asked about a card, not that a particular
 * player did, mid-game, from their address.
 */

import { apiMessage } from "../retryAfter";

export class CardError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api/cards";

async function cards<T>(path: string, params: Record<string, string>): Promise<T> {
  const r = await fetch(`${BASE}${path}?${new URLSearchParams(params)}`);
  if (!r.ok) {
    const detail = await r
      .json()
      .then((d: { detail?: string }) => d.detail)
      .catch(() => undefined);
    throw new CardError(
      r.status,
      apiMessage(r.status, detail ?? r.statusText, r.headers.get("Retry-After")),
    );
  }
  return r.json() as Promise<T>;
}

export interface Ruling {
  /** ISO date the ruling was published. */
  at: string | null;
  text: string;
  /** "wotc" for an official ruling, "scryfall" for their own annotation. Which
   *  one is speaking matters when a table is arguing about it. */
  source: string | null;
}

export interface CardRulings {
  name: string;
  typeLine: string | null;
  manaCost: string | null;
  oracleText: string | null;
  setName: string | null;
  /** Always present, even when `rulings` is empty — "no rulings" is an answer
   *  people want to check for themselves. */
  scryfallUrl: string;
  rulings: Ruling[];
}

export interface Suggestions {
  suggestions: string[];
  /** False while the card-name index has never been built. "Still loading the
   *  card list" and "no such card" are different problems, and only one of
   *  them is the player's. */
  ready: boolean;
}

export const suggestCards = (q: string) => cards<Suggestions>("/suggest", { q });

export const getRulings = (name: string) => cards<CardRulings>("/rulings", { name });
