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
 */
export function carouselEntries(players: PlayerInfo[]): CarouselEntry[] {
  const entries: CarouselEntry[] = [];
  const me = players.find((p) => p.isMe);
  if (me) entries.push({ pid: me.pid, name: me.name, isMe: true, card: me.card });
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
