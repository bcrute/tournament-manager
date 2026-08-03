/**
 * What a scanned QR or a pasted invitation actually contains.
 *
 * Split from the scanner component because this is the part with rules worth
 * testing: the component is camera plumbing, this decides whether a payload is
 * a room at all. A QR in the wild is usually somebody's wifi or a menu.
 *
 * A room is identified by 128 random bits in base64url — `rooms.url_id`. That
 * replaced a five-character code, which was short enough to read across a table
 * and therefore short enough to walk. Two consequences show up here:
 *
 * - **Case is meaningful.** The old code was upper-cased on the way in. Doing
 *   that to base64url destroys it, so nothing here changes what it was given.
 * - **The identifier travels in a fragment**, `…/table#r/<id>`, not a query.
 *   Fragments are never sent to a server, so an invitation cannot land in
 *   uvicorn's or Caddy's access log. The query form is still read, because
 *   links already in the world have to keep working, but nothing produces it.
 */

/** base64url, as `secrets.token_urlsafe(16)` emits it. */
const ROOM_ID = /^[A-Za-z0-9_-]{16,64}$/;

/** The fragment an invitation carries: `#r/<id>`. */
const FRAGMENT = /^#?r\/([A-Za-z0-9_-]{16,64})$/;

function valid(value: string | null | undefined): string | null {
  const v = (value ?? "").trim();
  return ROOM_ID.test(v) ? v : null;
}

/**
 * A room id from anything a person might paste or scan: the bare identifier, a
 * full invitation link, or a link to the room itself.
 *
 * Returns null rather than guessing. Refusing is cheap; joining the wrong room
 * because something looked close enough is not.
 */
export function roomIdFromScan(raw: string): string | null {
  const trimmed = (raw ?? "").trim();
  if (!trimmed) return null;

  const bare = valid(trimmed);
  if (bare) return bare;

  const loose = trimmed.match(FRAGMENT);
  if (loose) return valid(loose[1]);

  try {
    const url = new URL(trimmed);
    const fromFragment = url.hash.match(FRAGMENT);
    if (fromFragment) return valid(fromFragment[1]);
    // the room's own address, which is now also an invitation
    const path = url.pathname.match(/\/table\/r\/([A-Za-z0-9_-]{16,64})\/?$/);
    if (path) return valid(path[1]);
    // superseded by the fragment, still honoured for links already shared
    return valid(url.searchParams.get("join"));
  } catch {
    /* not a URL */
  }
  return null;
}

/** The link to share for a room. The id rides in the fragment. */
export function invitationLink(origin: string, roomId: string): string {
  return `${origin}/table#r/${roomId}`;
}
