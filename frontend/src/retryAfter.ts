/**
 * Turn a 429 into something a person can act on.
 *
 * The server's own detail is "too many requests — slow down", which is true
 * and useless: the one thing the user wants to know is whether to wait ten
 * seconds or go home. `Retry-After` carries that, so the three API layers
 * fold it into the message rather than each inventing their own copy.
 *
 * This matters most at the table. The room lookups share a budget sized for a
 * whole venue arriving at once (`docs/security.md`, rate limiting), so a
 * player who trips it is usually behind a shop's NAT with forty other people
 * — not doing anything wrong, and owed an explanation rather than a scolding.
 */

/** "in about 2 minutes", "in 45 seconds" — deliberately vague past a minute. */
export function waitPhrase(seconds: number): string {
  if (seconds <= 1) return "in a moment";
  if (seconds < 60) return `in ${Math.ceil(seconds)} seconds`;
  const minutes = Math.ceil(seconds / 60);
  return minutes === 1 ? "in about a minute" : `in about ${minutes} minutes`;
}

/**
 * The message to show for a failed response. Everything but 429 passes its own
 * detail through untouched — this only ever adds the wait.
 */
export function apiMessage(status: number, detail: string, retryAfter: string | null): string {
  if (status !== 429) return detail;
  const seconds = Number(retryAfter);
  // A missing or malformed header must not produce "in NaN seconds"; falling
  // back to the plain detail is worse copy but never wrong.
  if (!retryAfter || !Number.isFinite(seconds) || seconds <= 0) {
    return "Too many requests from this network. Try again shortly.";
  }
  return `Too many requests from this network. Try again ${waitPhrase(seconds)}.`;
}
