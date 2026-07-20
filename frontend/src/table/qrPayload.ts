/**
 * What a scanned QR actually contains, and whether it's one of ours.
 *
 * Split from the scanner component because this is the part with rules worth
 * testing: the component is camera plumbing, this decides whether a payload is
 * a room at all. A QR in the wild is usually somebody's wifi or a menu.
 */

const BARE = /^[A-Za-z0-9]{5}$/;

export function codeFromScan(raw: string): string | null {
  const trimmed = raw.trim();
  if (BARE.test(trimmed)) return trimmed.toUpperCase();
  try {
    const url = new URL(trimmed);
    const join = url.searchParams.get("join");
    if (join && BARE.test(join)) return join.toUpperCase();
    // only the room path: a tournament code is also five characters, and
    // joining the wrong thing is worse than refusing
    const m = url.pathname.match(/\/table\/r\/([A-Za-z0-9]{5})$/);
    if (m) return m[1].toUpperCase();
  } catch {
    /* not a URL */
  }
  return null;
}
