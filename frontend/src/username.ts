/**
 * Username suggestions.
 *
 * Most people reach for their email address because thinking of a username on
 * the spot is genuinely annoying. Telling them not to, without handing them
 * something to use instead, just adds friction and they'll type the email
 * anyway. So the "@" warning ships with a button that fills the field.
 *
 * Design constraints:
 * - **No dependency.** Two short word lists beat a package for this.
 * - **Readable aloud.** Someone may have to tell a friend their username at a
 *   table, so no leetspeak and no ambiguous characters.
 * - **Nothing that could describe a person.** No physical traits, no
 *   nationalities, no anything that lands badly when paired with a random
 *   noun. These combine unsupervised.
 * - **Not obviously generated.** `swift-lantern-27` reads like a name someone
 *   picked; `user_8f3a` reads like a database row.
 */

/** Deliberately mundane and concrete — evocative words produce silly pairs. */
const ADJECTIVES = [
  "amber", "brave", "brisk", "calm", "clever", "copper", "crimson", "curious",
  "daring", "dusty", "eager", "easy", "fabled", "fleet", "frosty", "gentle",
  "gilded", "golden", "hidden", "humble", "idle", "iron", "jolly", "keen",
  "lucky", "merry", "mellow", "misty", "noble", "olive", "patient", "polar",
  "quiet", "rapid", "rustic", "silver", "sleepy", "solar", "spare", "steady",
  "stony", "sunny", "swift", "tidy", "velvet", "wandering", "wild", "witty",
];

/** Objects and creatures, not people — a noun for a person invites a pairing
 *  that reads as a description of whoever holds it. */
const NOUNS = [
  "anchor", "acorn", "badger", "beacon", "bramble", "cedar", "cinder", "comet",
  "compass", "crane", "dagger", "ember", "falcon", "fathom", "ferry", "flint",
  "garnet", "harbor", "heron", "hollow", "kestrel", "lantern", "ledger", "loom",
  "marble", "meadow", "mortar", "orchard", "otter", "pebble", "quarry", "quill",
  "raven", "ridge", "sable", "sextant", "shale", "sparrow", "spindle", "thicket",
  "timber", "tinder", "vellum", "walnut", "willow", "wharf", "yarrow", "zephyr",
];

function pick<T>(list: T[]): T {
  // crypto.getRandomValues rather than Math.random: not because this is a
  // secret, but because it's already how the app generates default names and
  // the modulo bias on a 48-item list is immaterial either way.
  const b = crypto.getRandomValues(new Uint8Array(1))[0];
  return list[b % list.length];
}

/**
 * A suggestion like `swift-lantern-27`.
 *
 * ~48 × 48 × 90 ≈ 207,000 combinations — plenty for collision-avoidance at
 * this scale, and the server rejects a duplicate anyway, at which point the
 * caller just asks for another.
 */
export function suggestUsername(): string {
  const n = 10 + (crypto.getRandomValues(new Uint8Array(1))[0] % 90); // 10–99
  return `${pick(ADJECTIVES)}-${pick(NOUNS)}-${n}`;
}

/** Does this look like an email address? Used to prompt, never to block. */
export function looksLikeEmail(value: string): boolean {
  return value.includes("@");
}

export const WORD_COUNTS = { adjectives: ADJECTIVES.length, nouns: NOUNS.length };
