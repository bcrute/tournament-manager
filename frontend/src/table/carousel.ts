import { CardInfo, PlayerInfo } from "./api";

export interface CarouselEntry {
  pid: number;
  name: string;
  isMe: boolean;
  card: CardInfo | null;
}

/**
 * Cards you may look at on the card screen: yours first, then every player
 * whose identity is public, in seat order. Hidden players never appear.
 *
 * `myCard` is a separate argument because your own card is **not** in
 * `players`. The server masks every unrevealed identity in that array —
 * including your own row, on purpose, since the array is the same shape for
 * everyone — and serves your card once, on `state.me.card`. Reading it from
 * your row instead yields `null`, and the hold-to-peek gesture then flips a
 * card back over to reveal another card back. It shipped that way for two
 * weeks; the unit tests missed it because their fixtures put a card on the
 * caller's own row, where the real server never does.
 */
export function carouselEntries(
  players: PlayerInfo[],
  myCard: CardInfo | null,
): CarouselEntry[] {
  const entries: CarouselEntry[] = [];
  const me = players.find((p) => p.isMe);
  if (me) entries.push({ pid: me.pid, name: me.name, isMe: true, card: myCard });
  for (const p of players) {
    if (p.isMe || !p.card) continue;
    entries.push({ pid: p.pid, name: p.name, isMe: false, card: p.card });
  }
  return entries;
}

/** Wrap an index by `delta` steps around a list of `len` items. */
export function step(index: number, delta: number, len: number): number {
  if (len <= 0) return 0;
  return (((index + delta) % len) + len) % len;
}

/** Keep an index inside the list as it grows and shrinks. */
export function clampIndex(index: number, len: number): number {
  if (len <= 0) return 0;
  return Math.min(Math.max(index, 0), len - 1);
}

/** Where a given player sits in the carousel, or -1 when their card is hidden. */
export function indexOfPid(entries: CarouselEntry[], pid: number): number {
  return entries.findIndex((e) => e.pid === pid);
}
