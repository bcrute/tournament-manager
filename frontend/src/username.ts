/**
 * Name suggestions — for the table, and for an account.
 *
 * Two jobs, one word list. A player at a table needs a name before they can
 * sit down, and someone signing up needs a username; in both cases the app
 * offers one so nobody has to invent one on the spot (and, for accounts, so
 * nobody reaches for their email address instead).
 *
 * **These are meant to be funny.** An earlier version kept the pairs
 * deliberately mundane — `swift-lantern-27` — on the theory that evocative
 * words produce silly results. They do, and at a game night that is the point:
 * `Grumpy Platypus 42` is a name someone reads out and laughs at, which is
 * worth more here than one that reads like a Bond film.
 *
 * Funny still has rules, because these combine unsupervised and land on a
 * real person:
 * - **Nouns are animals, food and objects — never people.** A noun for a
 *   person turns every adjective into a description of whoever holds it.
 * - **No adjective that could describe a body, a mind, or where someone is
 *   from.** `wobbly` is funny about a walrus and cruel about a person, so the
 *   list stays with words that only read as whimsy once attached to a duck.
 * - **Readable aloud.** Someone has to say this across a table: no leetspeak,
 *   no ambiguous characters.
 * - **Short enough to fit.** A table name is capped at 24 characters, so the
 *   longest possible pairing plus a number has to fit inside that.
 */

/** Whimsical, and harmless once attached to a marmot. Max 8 characters. */
const ADJECTIVES = [
  "bashful", "bouncy", "brave", "bumbling", "chatty", "cheerful", "clumsy",
  "cranky", "crafty", "cuddly", "curious", "dapper", "daring", "dramatic",
  "dreamy", "feisty", "fluffy", "frantic", "gallant", "giggly", "glorious",
  "goofy", "grumpy", "hungry", "jaunty", "jazzy", "jittery", "jolly", "lucky",
  "majestic", "mighty", "nimble", "noisy", "peppy", "perky", "plucky",
  "prickly", "puzzled", "rowdy", "rusty", "sassy", "scrappy", "sleepy",
  "snazzy", "sneaky", "sparkly", "spicy", "spooky", "squeaky", "squishy",
  "sturdy", "swanky", "wiggly", "wobbly", "zany", "zesty", "zippy",
];

/** Creatures, snacks and objects — never a word for a person. Max 10. */
const NOUNS = [
  "alpaca", "axolotl", "badger", "bagel", "banjo", "beaver", "biscuit",
  "burrito", "cactus", "capybara", "chinchilla", "dingo", "donkey", "dumpling",
  "ferret", "gecko", "gibbon", "gopher", "hedgehog", "hippo", "iguana",
  "kazoo", "koala", "lemur", "llama", "manatee", "marmot", "meatball",
  "meerkat", "mongoose", "moose", "muffin", "narwhal", "newt", "noodle",
  "ocelot", "octopus", "otter", "panda", "pancake", "pangolin", "pelican",
  "penguin", "pickle", "platypus", "pretzel", "pufferfish", "quokka",
  "raccoon", "sloth", "spatula", "tapir", "teapot", "toaster", "toucan",
  "trombone", "turnip", "waffle", "walrus", "wombat", "yak",
];

function pick<T>(list: T[]): T {
  // crypto.getRandomValues rather than Math.random: not because this is a
  // secret, but because it's already how the app generates tokens and the
  // modulo bias on a list this size is immaterial either way.
  const b = crypto.getRandomValues(new Uint8Array(1))[0];
  return list[b % list.length];
}

/** 10–99. Two digits keep the name short enough to say and to fit the field. */
function suffix(): number {
  return 10 + (crypto.getRandomValues(new Uint8Array(1))[0] % 90);
}

/**
 * A username like `sneaky-platypus-42`.
 *
 * Lowercase and hyphenated, because a username gets typed and spelled out.
 * ~57 × 61 × 90 ≈ 313,000 combinations — plenty at this scale, and the server
 * rejects a duplicate anyway, at which point the caller asks for another.
 */
export function suggestUsername(): string {
  return `${pick(ADJECTIVES)}-${pick(NOUNS)}-${suffix()}`;
}

/**
 * A table name like `Sneaky Platypus 42`.
 *
 * Spaced and capitalised: this one is read off a screen by the other players
 * rather than typed, so it should look like a name, not a slug. Fits the
 * 24-character limit at the longest possible pairing (8 + 10 + 2 + spaces).
 */
export function suggestTableName(): string {
  const cap = (w: string) => w[0].toUpperCase() + w.slice(1);
  return `${cap(pick(ADJECTIVES))} ${cap(pick(NOUNS))} ${suffix()}`;
}

/**
 * A tournament name like `Sneaky Platypus 42`.
 *
 * The same shape, and deliberately the same lists: an organizer naming Friday
 * night wants something to accept or type over, not an empty field between
 * them and their event. A separate export so call sites say which thing they
 * are naming.
 */
export const suggestEventName = suggestTableName;

/** Does this look like an email address? Used to prompt, never to block. */
export function looksLikeEmail(value: string): boolean {
  return value.includes("@");
}

export const WORD_COUNTS = { adjectives: ADJECTIVES.length, nouns: NOUNS.length };
export const WORDS = { ADJECTIVES, NOUNS };
